import asyncio
import ipaddress
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx

from app.lib.ip_addr_utils import is_valid_ip

log = logging.getLogger("rdap")

IANA_URLS = {
    "ipv4": "https://data.iana.org/rdap/ipv4.json",
    "ipv6": "https://data.iana.org/rdap/ipv6.json",
}

IPAddr = ipaddress.IPv4Address | ipaddress.IPv6Address


@dataclass
class _Table:
    """
    Clase de las tablas bootstrap en memoria.
    """

    v4: list[tuple[ipaddress.IPv4Network, str]] = field(default_factory=list)
    v6: list[tuple[ipaddress.IPv6Network, str]] = field(default_factory=list)

    @classmethod
    def build(cls, docs: dict[str, dict]) -> _Table:
        """
        Construye las tablas desde los docs de la IANA.
        """
        t = cls()
        for doc in docs.values():
            if not doc:
                continue
            for entry in doc.get("services", []):
                patterns, servers = entry[0], entry[1]
                if not servers:
                    continue
                base = servers[0].rstrip("/") + "/"
                for cidr in patterns:
                    net = ipaddress.ip_network(cidr)
                    (t.v4 if net.version == 4 else t.v6).append((net, base))
        return t

    def resolve(self, addr: IPAddr) -> str | None:
        """
        Resuelve por método del prefijo más largo
        para devolver la URL correspondiente a la IP solicitada.
        """
        table = self.v4 if addr.version == 4 else self.v6
        best_url, best_len = None, -1
        for net, base in table:
            if net.prefixlen > best_len and addr in net:
                best_len, best_url = net.prefixlen, base
        return best_url


class BootstrapStore:
    """
    Almacena y gestiona la vida del bootstrap como servicio.
    """

    def __init__(self) -> None:
        """
        Inicializa con tabla vacía.
        """
        self._table: _Table | None = None

    def swap(self, table: _Table) -> None:
        """
        Intercambio atómico de la tabla.
        """
        self._table = table

    def rdap_url_for(self, ip: str) -> str | None:
        """
        Devuelve la URL del servidor RDAP correspondiente a la IP.
        """
        if not is_valid_ip(ip) or self._table is None:
            return None
        base = self._table.resolve(ipaddress.ip_address(ip))
        return f"{base}ip/{ip}" if base else None


class BootstrapUpdater:
    """
    Gestiona el ciclo de actualizaciones para el bootstrap.
    """

    def __init__(
        self,
        store: BootstrapStore,
        data_dir: str | Path,
        interval_hours: float = 24.0,
        client_factory=None,
    ) -> None:
        self.store = store
        self.data_dir = Path(data_dir)
        self.interval_hours = interval_hours
        self._client_factory = client_factory or (
            lambda: httpx.AsyncClient(
                timeout=15.0,
                follow_redirects=True,
                headers={"User-Agent": "whoami-diagnostic (by 50512)"},
            )
        )
        self._docs: dict[str, dict] = {}
        self._task: asyncio.Task | None = None

    def _doc_path(self, name: str) -> Path:
        """
        Ruta del documento.
        """
        return self.data_dir / f"{name}.json"

    def _meta_path(self, name: str) -> Path:
        """
        Ruta de la metadata.
        """
        return self.data_dir / f"{name}.meta.json"

    @staticmethod
    def _usable(name: str, doc) -> bool:
        """
        Intenta construir la tabla desde el documento.
        Devuelve `bool` en base a éxito o fracaso.
        """
        try:
            t = _Table.build({name: doc})
        except Exception:
            return False
        return bool(t.v4 or t.v6)

    @staticmethod
    def _write(path: Path, text: str) -> None:
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

    def _read_meta(self, name: str) -> dict:
        """
        Lee la metadata guardada.
        """
        path = self._meta_path(name)
        try:
            return json.loads(path.read_text()) if path.exists() else {}
        except Exception:
            return {}

    def _load_local(self, name: str) -> dict | None:
        """
        Carga las tablas desde el documento local. De no existir, devuelve `None`.
        """
        path = self._doc_path(name)
        try:
            if path.exists():
                doc = json.loads(path.read_text())
                if self._usable(name, doc):
                    return doc
        except Exception:
            log.exception(f"No se pudo leer {path}")
        return None

    def _next_check_from(self, res: httpx.Response, checked_at: float) -> float:
        """
        Devuelve el timestamp de la proxima verificación.
        De no existir la cabecera correspondiente o estar
        mal formada, devuelve el proximo timestamp basado
        en el intervalo del updater.
        """
        for part in res.headers.get("Cache-Control", "").split(","):
            part = part.strip().lower()
            if part.startswith("max-age="):
                try:
                    return checked_at + int(part.split("=", 1)[1])
                except ValueError:
                    log.exception("cabecera 'Cache-Control' mal formada o inexistente")
        exp = res.headers.get("Expires")
        if exp:
            try:
                return parsedate_to_datetime(exp).timestamp()
            except (TypeError, ValueError):
                log.exception("cabecera 'Expires' mal formada o inexistente")
        return checked_at + self.interval_hours * 3600

    async def _fetch(
        self, client: httpx.AsyncClient, name: str, *, force: bool = False
    ) -> dict | None:
        """
        Intenta fetch a la fuente de la IANA.
        Si esta aún en ventana de espera y no se fuerza,
        omite petición. Envía las peticiones con cabeceras
        condicionales para no descargar nada si no cambió el
        contenido.
        """
        meta = self._read_meta(name)
        now = time.time()

        if not force and now < meta.get("next_check", 0):
            log.info(f"{name} dentro de ventana de espera")
            return None

        # Para verificar si el contenido difiere
        headers = {}
        if meta.get("etag"):
            headers["If-None-Match"] = meta["etag"]
        if meta.get("last_modified"):
            headers["If-Modified-Since"] = meta["last_modified"]

        res = await client.get(IANA_URLS[name], headers=headers)

        if res.status_code == 304:
            # Contenido no cambió. Se actualiza la ventana y se mantiene los docs actuales
            meta["checked_at"] = now
            meta["next_check"] = self._next_check_from(res, now)
            self._write(self._meta_path(name), json.dumps(meta))
            log.info(f"{name} sin cambios")
            return None

        res.raise_for_status()

        doc = res.json()
        if not self._usable(name, doc):
            log.error(f"{name} no construye, se descarta y mantiene doc actual.")
            raise ValueError(f"{name} no construye la tabla")

        self._write(self._doc_path(name), res.text)
        self._write(
            self._meta_path(name),  # Actualiza la metadata
            json.dumps(
                {
                    "etag": res.headers.get("ETag"),
                    "last_modified": res.headers.get("Last-Modified"),
                    "checked_at": now,
                    "next_check": self._next_check_from(res, now),
                }
            ),
        )
        return doc

    async def refresh_once(self, *, force: bool = False) -> None:
        """
        Refresca las tablas (de existir nuevas). De existir nuevas, las descarga y reemplaza.
        """
        changed = False
        async with self._client_factory() as client:
            for name in IANA_URLS:
                try:
                    doc = await self._fetch(client, name, force=force)
                    if doc is not None:
                        self._docs[name] = doc
                        changed = True
                        log.info(f"{name} actualizado")
                except Exception:
                    log.exception(f"Fallo actualizando {name}")
        if changed:
            try:
                self.store.swap(_Table.build(self._docs))
                log.info("Tabla completa actualizada")
            except Exception:
                log.exception("Fallo al reconstruir la tabla.")

    async def start(self) -> None:
        """
        Carga las tablas locales de existir y crea el loop de actualización.
        """
        for name in IANA_URLS:
            doc = self._load_local(name)
            if doc is None:
                log.error(f"No existe {name} local")
            else:
                self._docs[name] = doc
        if self._docs:
            try:
                self.store.swap(_Table.build(self._docs))
                log.info(f"Tabla inicial cargada: {", ".join(self._docs)}")
            except Exception as e:
                log.exception(f"Tabla no cargada: {e}")
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
                        self._read_meta(name).get("next_check", 0) for name in IANA_URLS
                    )
                    if t > now
                ]
                log.debug(f"Proxima actualización por tabla: {upcoming}")
                wake = min(upcoming) if upcoming else now + self.interval_hours * 3600
                delay = min(max(wake - now, 300.0), self.interval_hours * 3600 * 2)
                log.debug(f"Despertar: {wake}; Esperando por: {delay}")
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
