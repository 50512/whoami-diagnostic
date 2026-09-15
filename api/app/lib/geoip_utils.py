import asyncio
import logging
import os
from dataclasses import dataclass

import geoip2.database
from geoip2.errors import AddressNotFoundError
from maxminddb import MODE_MEMORY

from app.lib.ip_addr_utils import is_valid_ip

log = logging.getLogger("geoip")

MMDB_ATTRIBUTIONS = {
    "maxmind": {
        "source": "maxmind-geolite2",
        "text": "This product includes GeoLite2 Data created by MaxMind, available from https://www.maxmind.com.",
        "url": "https://www.maxmind.com",
    }
}


@dataclass
class _Entry:
    """
    Clase de entradas para almacenar cada `mmdb` con su firma para actualización en caliente.
    """

    path: str
    reader: geoip2.database.Reader | None = None
    sign: tuple | None = None  # Firma (inode, mtime, size)


def _stat_sign(path: str) -> tuple | None:
    """
    Genera la firma de un archivo.
    """
    try:
        stat = os.stat(path)
        sign = (stat.st_ino, stat.st_mtime_ns, stat.st_size)
        log.debug(f"Firma de {path}: {sign}")
        return sign
    except FileNotFoundError:
        return None


def _open(path: str) -> geoip2.database.Reader:
    """
    Carga en memoria la `mmdb`.
    """
    return geoip2.database.Reader(path, mode=MODE_MEMORY)


class GeoIPManager:
    """
    Clase administradora de todo el ciclo de vida y consulta para las MaxMind Databases.
    """

    def __init__(self, paths: dict[str, str], poll_interval: float = 30.0):
        self._entries = {name: _Entry(path) for name, path in paths.items()}
        self._poll_interval = poll_interval
        self._lock = asyncio.Lock()  # Solo para recarga
        self._task: asyncio.Task | None = None

    # --------- Reader ---------
    def reader(self, name: str) -> geoip2.database.Reader:
        """
        Devuelve el lector cargado en memoria.
        """
        reader = self._entries[name].reader
        if reader is None:
            raise RuntimeError(f"geoip db '{name}' no cargada")
        return reader

    # --------- Recarga en caliente ---------
    async def _reload(self, name: str) -> None:
        """
        Recarga en caliente la base de datos `mmdb` de manera atómica.
        Solo actualiza si la firma actual difiere de la guardada.
        """
        entry = self._entries[name]
        sign = _stat_sign(entry.path)

        if sign is None or sign == entry.sign:
            return

        try:
            new = await asyncio.to_thread(_open, entry.path)
        except Exception:
            log.exception(
                f"fallo abriendo {entry.path}; Se conserva el reader anterior"
            )
            return

        old = entry.reader
        entry.reader = new
        entry.sign = sign

        if old is not None:
            # Cierra lector anterior
            old.close()
        log.info(f"mmdb {name} recargada (build={new.metadata().build_epoch})")

    async def load_all(self) -> None:
        """
        Carga todas las databases en memoria.
        """
        async with self._lock:
            for name in self._entries:
                await self._reload(name)

    async def _poll(self) -> None:
        """
        Ejecuta poll cada `poll_interval` segundos para mantener la base al día.
        """
        while True:
            await asyncio.sleep(self._poll_interval)
            async with self._lock:
                for name in self._entries:
                    await self._reload(name)

    async def start(self) -> None:
        """
        Carga todas las `mmdb` y crea el loop de actualización.
        """
        await self.load_all()
        self._task = asyncio.create_task(self._poll())

    async def stop(self) -> None:
        """
        Detiene el bucle de actualización y cierra los lectores en memoria.
        """
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        for entry in self._entries.values():
            if entry.reader:
                entry.reader.close()


def get_json_mmdb(
    ip: str, asn_reader: geoip2.database.Reader, city_reader: geoip2.database.Reader
) -> dict:
    """
    Regresa un JSON con los datos de la IP ingresada.
    De no ser válida, regresa esqueleto en `None`.
    Consulta las bases de datos ASN y CITY GeoLite2.
    """
    res = {
        "ip": ip,
        "asn": None,
        "asn_org": None,
        "cidr": None,
        "geolocation": {
            "country": {"name": None, "iso_code": None},
            "region": None,
            "city": None,
            "continent_code": None,
            "zip_code": None,
        },
        "location": {
            "latitude": None,
            "longitude": None,
            "accuracy_radius": None,
            "timezone": None,
        },
        "attributions": None,
    }

    if not is_valid_ip(ip):
        return res

    # --------- Consulta ASN ---------
    try:
        asn = asn_reader.asn(ip)
        log.debug(f"Consulta asn: {asn}")
        res["asn"] = asn.autonomous_system_number
        res["asn_org"] = asn.autonomous_system_organization
        if asn.network is not None:
            res["cidr"] = str(asn.network)
        res["attributions"] = MMDB_ATTRIBUTIONS
    except AddressNotFoundError:
        pass

    # --------- Consulta Geo ---------
    try:
        city = city_reader.city(ip)
        log.debug(f"Consulta city: {city}")
        geo = res["geolocation"]
        geo["country"]["name"] = city.country.name
        geo["country"]["iso_code"] = city.country.iso_code
        geo["region"] = city.subdivisions.most_specific.name
        geo["city"] = city.city.name
        geo["continent_code"] = city.continent.code
        geo["zip_code"] = city.postal.code

        loc = res["location"]
        loc["latitude"] = city.location.latitude
        loc["longitude"] = city.location.longitude
        loc["accuracy_radius"] = city.location.accuracy_radius
        loc["timezone"] = city.location.time_zone

        res["attributions"] = MMDB_ATTRIBUTIONS
    except AddressNotFoundError:
        pass

    return res


def get_resolver_mmdb(ip: str, asn_reader: geoip2.database.Reader) -> dict:
    """
    Función dedicada para datos de resolvers DNS.
    Devuelve solo datos de ASN si la IP es válida.
    """
    res = {
        "ip": ip,
        "asn": None,
        "asn_org": None,
        "cidr": None,
    }
    if not is_valid_ip(ip):
        return res
    try:
        asn = asn_reader.asn(ip)
        log.debug(f"Consulta asn para dns: {asn}")
        res["asn"] = asn.autonomous_system_number
        res["asn_org"] = asn.autonomous_system_organization
        if asn.network is not None:
            res["cidr"] = str(asn.network)
    except AddressNotFoundError:
        pass
    return res
