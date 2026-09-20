import logging
import re

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from geoip2.database import Reader

from app.lib.geoip_utils import MMDB_ATTRIBUTIONS, get_resolver_mmdb

log = logging.getLogger("fastapi.dnsleak")
router = APIRouter(prefix="/dns-leak", tags=["dns-leak"])

TEST_ID_RE = re.compile(r"^[0-9a-f]{32}$")
LEAK_KEY_PREFIX = "dnsleak:"


@router.get("/{test_id}")
async def dns_leak(test_id: str, request: Request):
    """
    Lee en redis la clave con el test_id correspondiente.
    Si el token no cumple, se rechaza con 400. Responde 404
    si no se encuentra los datos con el token (muy temprano o muy tarde).
    """
    test_id = test_id.lower()
    if not TEST_ID_RE.match(test_id):
        return JSONResponse(
            {"error": "invalid test id"}, status_code=status.HTTP_400_BAD_REQUEST
        )

    redis = request.app.state.redis
    try:
        log.debug(f"Leyendo token: {test_id}")
        ips = await redis.smembers(f"{LEAK_KEY_PREFIX}{test_id}")
    except Exception:
        log.exception("Error al consultar redis")
        return JSONResponse(
            {"error": "dns leak unavailable"},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    if not ips:
        return JSONResponse(
            {"error": "not found entries with token"},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    asn_reader = request.app.state.geoip.reader("asn")
    log.debug(f"Lista de IP: {ips}")
    log.debug(f"Lista de IP ordenadas: {sorted(ips)}")
    resolvers = get_resolvers_mmdb(ips, asn_reader)

    return JSONResponse(
        {
            "test_id": test_id,
            "count": len(resolvers),
            "resolvers": resolvers,
            "attributions": MMDB_ATTRIBUTIONS,
        }
    )


def get_resolvers_mmdb(ips: list[str], asn_reader: Reader) -> dict:
    """
    Itera sobre una lista de IPs y los unifica bajo ASN como identificador de resolver individual.
    """
    resolvers = [get_resolver_mmdb(ip, asn_reader) for ip in sorted(ips)]

    deduped: dict = {}
    for resolver in resolvers:
        asn = resolver["asn"]
        entry = deduped.get(asn)

        if entry is None:
            log.debug(f"Creando clave asn: {asn}")
            entry = deduped[asn] = {
                "asn": asn,
                "asn_org": resolver["asn_org"],
                "ips": set(),
                "cidrs": set(),
            }
        entry["ips"].add(resolver["ip"])
        entry["cidrs"].add(resolver["cidr"])

    log.debug(f"deduped: {deduped}")
    for entry in deduped.values():

        entry["ips"] = sorted(entry["ips"])
        entry["cidrs"] = sorted(entry["cidrs"])

    return dict(sorted(deduped.items()))
