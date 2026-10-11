import logging
import re

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from app.lib.geoip_utils import (MMDB_ATTRIBUTIONS, get_ecs_mmdb,
                                 get_resolver_mmdb)
from app.lib.ip_addr_utils import ip_key, net_key

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
        key = LEAK_KEY_PREFIX + test_id
        async with redis.pipeline(transaction=False) as pipe:
            ips, ecs_members = await pipe.smembers(key).smembers(f"{key}:ecs").execute()
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

    log.debug(f"Lista de IP: {ips}")
    if ecs_members:
        log.debug(f"ECS: {ecs_members}")
    resolvers = get_resolvers_mmdb(ips, ecs_members, request)

    return JSONResponse(
        {
            "test_id": test_id,
            "count": len(resolvers),
            "resolvers": resolvers,
            "attributions": MMDB_ATTRIBUTIONS,
        }
    )


def get_resolvers_mmdb(ips: set[str], ecs_members: set[str], request: Request) -> dict:
    """
    Itera sobre una lista de IPs y los unifica bajo
    resolver conocido o ASN_ORG como identificador
    de resolver individual.
    """
    asn_reader = request.app.state.geoip.reader("asn")
    city_reader = request.app.state.geoip.reader("city")
    resolvers_store = request.app.state.resolvers_store
    resolvers = [get_resolver_mmdb(ip, asn_reader) for ip in ips]
    ecs_by_ip: dict[str, set[str]] = {}

    for member in ecs_members:
        resolver_ip, cidr = member.split("|", 1)
        ecs_by_ip.setdefault(resolver_ip, set()).add(cidr)
    log.debug(f"ECS BY IP: {ecs_by_ip}")

    ecs_cache: dict[str, dict] = {}

    deduped: dict = {}
    for resolver in resolvers:
        asn_org = resolver["asn_org"]
        label = resolvers_store.lookup(resolver["ip"])
        group_key = label or asn_org or "Unknown"
        entry = deduped.get(group_key)

        if entry is None:
            log.debug(f"Creando clave de grupo: {group_key}")
            entry = deduped[group_key] = {
                "asns": set(),
                "asns_org": set(),
                "ips": set(),
                "cidrs": set(),
                "ecs": {},
            }

        for cidr in ecs_by_ip.get(resolver["ip"], ()):
            if cidr not in ecs_cache:
                ecs_cache[cidr] = get_ecs_mmdb(cidr, asn_reader, city_reader)
            entry["ecs"].setdefault(cidr, ecs_cache[cidr])

        if resolver["asn"] is not None:
            entry["asns"].add(resolver["asn"])
        if asn_org:
            entry["asns_org"].add(asn_org)
        entry["ips"].add(resolver["ip"])
        if resolver["cidr"]:
            entry["cidrs"].add(resolver["cidr"])

    log.debug(f"deduped: {deduped}")
    for entry in deduped.values():

        entry["asns"] = sorted(entry["asns"])
        entry["asns_org"] = sorted(entry["asns_org"])
        entry["ips"] = sorted(entry["ips"], key=ip_key)
        entry["cidrs"] = sorted(entry["cidrs"], key=net_key)
        entry["ecs"] = [entry["ecs"][c] for c in sorted(entry["ecs"], key=net_key)]

    return dict(sorted(deduped.items()))
