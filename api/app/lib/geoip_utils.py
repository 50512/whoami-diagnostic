import asyncio
import os
import logging
from dataclasses import dataclass

import geoip2.database
from geoip2.errors import AddressNotFoundError
from maxminddb import MODE_MEMORY

log = logging.getLogger("geoip")

@dataclass
class _Entry:
    path: str
    reader: geoip2.database.Reader | None = None
    sign: tuple | None = None # Firma (inode, mtime, size)


def _stat_sign(path: str) -> tuple | None:
    try:
        stat = os.stat(path)
        return (stat.st_ino, stat.st_mtime_ns, stat.st_size)
    except FileNotFoundError:
        return None


def _open(path: str) -> geoip2.database.Reader:
    return geoip2.database.Reader(path, mode=MODE_MEMORY)


class GeoIPManager:
    def __init__(self, paths: dict[str, str], poll_interval: float = 30.0):
        self._entries = {name: _Entry(path) for name, path in paths.items()}
        self._poll_interval = poll_interval
        self._lock = asyncio.Lock() # Solo para recarga
        self._task: asyncio.Task | None = None


    # --------- Reader ---------
    def reader(self, name: str) -> geoip2.database.Reader:
        reader = self._entries[name].reader
        if reader is None:
            raise RuntimeError(f"geoip db '{name}' no cargada")
        return reader


    # --------- Recarga en caliente ---------
    async def _reload(self, name:str) -> None:
        entry = self._entries[name]
        sign = _stat_sign(entry.path)

        if sign is None or sign == entry.sign:
            return

        try:
            new = await asyncio.to_thread(_open, entry.path)
        except Exception:
            log.exception(f"geoip: fallo abriendo {entry.path}; Se conserva el reader anterior")
            return

        old = entry.reader
        entry.reader = new
        entry.sign = sign

        if old is not None:
            old.close()
        log.info(f"geoip: '{name}' recargada (build={new.metadata().build_epoch})")


    async def load_all(self) -> None:
        async with self._lock:
            for name in self._entries:
                await self._reload(name)


    async def _poll(self) -> None:
        while True:
            await asyncio.sleep(self._poll_interval)
            async with self._lock:
                for name in self._entries:
                    await self._reload(name)


    async def start(self) -> None:
        await self.load_all()
        self._task = asyncio.create_task(self._poll())


    async def stop(self) -> None:
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
        ip: str,
        asn_reader: geoip2.database.Reader,
        city_reader: geoip2.database.Reader
    ) -> dict:
    res = {
        "ip": ip,
        "asn": None,
        "asn_org": None,
        "cidr": None,
        "geolocation": {
            "country": {
                "name": None,
                "iso_code": None
            },
            "region": None,
            "city": None,
            "continent_code": None,
            "zip_code": None,
        },
        "location": {
            "latitude": None,
            "longitude": None,
            "accuracy_radius": None,
            "timezone": None
        },
    }

    # --------- Consulta ASN ---------
    try:
        asn = asn_reader.asn(ip)
        res["asn"] = asn.autonomous_system_number
        res["asn_org"] = asn.autonomous_system_organization
        if asn.network is not None:
            res["cidr"] = str(asn.network)
    except AddressNotFoundError:
        pass
    except ValueError:
        return res

    # --------- Consulta Geo ---------
    try:
        city = city_reader.city(ip)
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
    except AddressNotFoundError:
        pass

    return res
