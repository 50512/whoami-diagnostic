import logging
import re

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

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
        log.exception(f"Error al consultar redis")
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
    resolvers = [get_resolver_mmdb(ip, asn_reader) for ip in sorted(ips)]

    return JSONResponse(
        {
            "test_id": test_id,
            "count": len(resolvers),
            "resolvers": resolvers,
            "attributions": MMDB_ATTRIBUTIONS,
        }
    )
