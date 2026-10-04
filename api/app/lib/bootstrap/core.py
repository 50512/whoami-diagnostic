import asyncio
import ipaddress
import json
import logging
import os
import tempfile
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx

from app.lib.ip_addr_utils import is_valid_ip

IPAddr = ipaddress.IPv4Address | ipaddress.IPv6Address
IPNet = ipaddress.IPv4Network | ipaddress.IPv6Network
Entry = tuple[IPNet, str]


def atomic_write(path: Path, text: str) -> None:
    """
    Escribe de manera atómica el archivo.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def next_check_from(
    res: httpx.Response,
    checked_at: float,
    fallback_s: float,
    log: logging.Logger | None = None,
) -> float:
    """
    Devuelve el timestamp de la proxima verificación.
    De no existir la cabecera correspondiente o estar
    mal formada, devuelve el proximo timestamp basado
    en el fallback.
    """
    log = log or logging.getLogger(__name__)
    directives: dict[str, str] = {}
    for part in res.headers.get("Cache-Control", "").split(","):
        key, _, value = part.strip().lower().partition("=")
        if value:
            directives[key] = value
    for key in ("max-age", "s-maxage"):
        if key in directives:
            try:
                return checked_at + int(directives[key])
            except ValueError:
                log.exception(f"cabecera 'Cache-Control' con '{key}' mal formado")
    exp = res.headers.get("Expires")
    if exp:
        try:
            return parsedate_to_datetime(exp).timestamp()
        except (TypeError, ValueError):
            log.exception("cabecera 'Expires' mal formada")
    return checked_at + fallback_s


@dataclass
class PrefixTable:
    """
    Tabla en memoria de prefijos IP -> valor (RDAP, etiqueta de resolver, etc.).
    """

    v4: list[tuple[ipaddress.IPv4Network, str]] = field(default_factory=list)
    v6: list[tuple[ipaddress.IPv6Network, str]] = field(default_factory=list)

    @classmethod
    def from_entries(cls, groups: Iterable[list[Entry]]) -> PrefixTable:
        """
        Construye la tabla a partir de varios grupos de entradas (uno por fuente).
        """
        t = cls()
        for entries in groups:
            for net, value in entries:
                (t.v4 if net.version == 4 else t.v6).append((net, value))
        return t

    def resolve(self, addr: IPAddr) -> str | None:
        """
        Resuelve por método del prefijo más largo
        para devolver el valor correspondiente a la IP solicitada.
        """
        table = self.v4 if addr.version == 4 else self.v6
        best_value, best_len = None, -1
        for net, value in table:
            if net.prefixlen > best_len and addr in net:
                best_len, best_value = net.prefixlen, value
        return best_value


class PrefixStore:
    """
    Contenedor de la tabla vigente. El updater la reemplaza con `swap`.
    """

    def __init__(self) -> None:
        """
        Inicializa con tabla vacía.
        """
        self._table: PrefixTable | None = None

    def swap(self, table: PrefixTable) -> None:
        """
        Intercambio atómico de la tabla.
        """
        self._table = table

    def lookup(self, ip: str) -> str | None:
        """
        Devuelve el valor asociado al prefijo más largo que contiene la IP.
        """
        if not is_valid_ip(ip) or self._table is None:
            return None
        return self._table.resolve(ipaddress.ip_address(ip))


@dataclass(frozen=True)
class Source:
    """
    Fuente remota de prefijos.
    `parse` recibe el cuerpo crudo (texto) y devuelve las entradas `(net, valor)`.
    """

    url: str
    parse: Callable[[str], list[Entry]]
    ext: str = "json"


class BootstrapUpdater:
    """
    Gestiona el ciclo de actualizaciones de un conjunto de fuentes que
    alimentan una única `PrefixTable`.
    """

    def __init__(
        self,
        store: PrefixStore,
        sources: dict[str, Source],
        data_dir: str | Path,
        interval_hours: float = 24.0,
        client_factory=None,
        logger_name: str = "bootstrap",
    ) -> None:
        self.store = store
        self.sources = sources
        self.data_dir = Path(data_dir)
        self.interval_hours = interval_hours
        self.log = logging.getLogger(logger_name)
        self._client_factory = client_factory or (
            lambda: httpx.AsyncClient(
                timeout=15.0,
                follow_redirects=True,
                headers={"User-Agent": "whoami-diagnostic (by 50512)"},
            )
        )
        self._entries: dict[str, list[Entry]] = {}
        self._task: asyncio.Task | None = None

    @property
    def _fallback_s(self) -> float:
        """
        Intervalo de respaldo en segundos.
        """
        return self.interval_hours * 3600

    def _doc_path(self, name: str) -> Path:
        """
        Ruta del documento.
        """
        return self.data_dir / f"{name}.{self.sources[name].ext}"

    def _meta_path(self, name: str) -> Path:
        """
        Ruta de la metadata.
        """
        return self.data_dir / f"{name}.meta.json"

    def _parse(self, name: str, text: str) -> list[Entry] | None:
        """
        Parsea el documento con el parser de la fuente.
        Devuelve `None` si falla o no produce entradas.
        """
        try:
            entries = self.sources[name].parse(text)
        except Exception:
            self.log.exception(f"{name} no parsea")
            return None
        return entries or None

    def _read_meta(self, name: str) -> dict:
        """
        Lee la metadata guardada.
        """
        path = self._meta_path(name)
        try:
            return json.loads(path.read_text()) if path.exists() else {}
        except Exception:
            return {}

    def _load_local(self, name: str) -> list[Entry] | None:
        """
        Carga las entradas desde el documento local. De no existir, devuelve `None`.
        """
        path = self._doc_path(name)
        try:
            if path.exists():
                return self._parse(name, path.read_text())
        except Exception:
            self.log.exception(f"No se pudo leer {path}")
        return None

    def _rebuild(self) -> None:
        """
        Reconstruye la tabla con todas las entradas vigentes y la intercambia.
        """
        self.store.swap(PrefixTable.from_entries(self._entries.values()))

    async def _fetch(
        self, client: httpx.AsyncClient, name: str, *, force: bool = False
    ) -> list[Entry] | None:
        """
        Intenta fetch a la fuente.
        Si esta aún en ventana de espera y no se fuerza,
        omite petición. Envía las peticiones con cabeceras
        condicionales para no descargar nada si no cambió el
        contenido (si la fuente las soporta).
        """
        meta = self._read_meta(name)
        now = time.time()

        if not force and now < meta.get("next_check", 0):
            self.log.info(f"{name} dentro de ventana de espera")
            return None

        # Para verificar si el contenido difiere
        headers = {}
        if meta.get("etag"):
            headers["If-None-Match"] = meta["etag"]
        if meta.get("last_modified"):
            headers["If-Modified-Since"] = meta["last_modified"]

        res = await client.get(self.sources[name].url, headers=headers)

        if res.status_code == 304:
            # Contenido no cambió. Se actualiza la ventana y se mantienen las entradas actuales
            meta["checked_at"] = now
            meta["next_check"] = next_check_from(res, now, self._fallback_s, self.log)
            atomic_write(self._meta_path(name), json.dumps(meta))
            self.log.info(f"{name} sin cambios")
            return None

        res.raise_for_status()

        entries = self._parse(name, res.text)
        if entries is None:
            self.log.error(f"{name} no construye, se descarta y mantiene doc actual.")
            raise ValueError(f"{name} no construye la tabla")

        atomic_write(self._doc_path(name), res.text)
        atomic_write(
            self._meta_path(name),  # Actualiza la metadata
            json.dumps(
                {
                    "etag": res.headers.get("ETag"),
                    "last_modified": res.headers.get("Last-Modified"),
                    "checked_at": now,
                    "next_check": next_check_from(res, now, self._fallback_s, self.log),
                }
            ),
        )
        return entries

    async def refresh_once(self, *, force: bool = False) -> None:
        """
        Refresca las fuentes. Si alguna cambió, reconstruye y reemplaza la tabla.
        """
        changed = False
        async with self._client_factory() as client:
            for name in self.sources:
                try:
                    entries = await self._fetch(client, name, force=force)
                    if entries is not None:
                        self._entries[name] = entries
                        changed = True
                        self.log.info(f"{name} actualizado")
                except Exception:
                    self.log.exception(f"Fallo actualizando {name}")
        if changed:
            try:
                self._rebuild()
                self.log.info("Tabla completa actualizada")
            except Exception:
                self.log.exception("Fallo al reconstruir la tabla.")

    async def start(self) -> None:
        """
        Carga las tablas locales de existir y crea el loop de actualización.
        """
        for name in self.sources:
            entries = self._load_local(name)
            if entries is None:
                self.log.error(f"No existe {name} local")
            else:
                self._entries[name] = entries
        if self._entries:
            try:
                self._rebuild()
                self.log.info(f"Tabla inicial cargada: {", ".join(self._entries)}")
            except Exception as e:
                self.log.exception(f"Tabla no cargada: {e}")
        self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        """
        Solicita actualizar las tablas en base a la metadata y
        con un máximo basado en el intervalo de horas del updater.
        """
        try:
            while True:
                await self.refresh_once()
                now = time.time()
                upcoming = [
                    t
                    for t in (
                        self._read_meta(name).get("next_check", 0)
                        for name in self.sources
                    )
                    if t > now
                ]
                self.log.debug(f"Proxima actualización por tabla: {upcoming}")
                wake = min(upcoming) if upcoming else now + self._fallback_s
                delay = min(max(wake - now, 300.0), self._fallback_s * 2)
                self.log.debug(f"Despertar: {wake}; Esperando por: {delay}")
                await asyncio.sleep(delay)
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        """
        Detiene el actualizador
        """
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
