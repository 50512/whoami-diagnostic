import logging
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import redis.asyncio as aioredis
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse

from app.lib.geoip_utils import (
    MMDB_ATTRIBUTIONS,
    GeoIPManager,
    get_json_mmdb,
    get_resolver_mmdb,
)
from app.lib.ip_addr_utils import is_valid_ip
from app.lib.rdap_bootstrap import BootstrapStore, BootstrapUpdater

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

IP_HOSTS = [os.environ.get("IPV4_HOST"), os.environ.get("IPV6_HOST")]
EXCLUDED_MIDDLEWARE_PATHS = ["/ready", "/info"]

GEOIP_PATH = os.environ.get("GEOIP_PATH", "/var/opt/GeoIP")
CLI_REGEX = re.compile(r"(?i)(curl|wget|python|httpie|aria2)")

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
LEAK_KEY_PREFIX = "dnsleak:"
TEST_ID_RE = re.compile(r"^[0-9a-f]{32}$")

ALLOWED_HEADERS = {
    "user-agent",
    "sec-ch-ua",
    "sec-ch-ua-mobile",
    "sec-ch-ua-platform",
    "accept-language",
    "accept",
    "accept-encoding",
    "dnt",
    "sec-gpc",
    "forwarded",
}

rdap_store = BootstrapStore()
rdap_updater = BootstrapUpdater(rdap_store, data_dir=Path("/data/rdap-bootstrap"))

log = logging.getLogger("fastapi.access")
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def get_plain_ip(request: Request) -> str:
    """
    Devuelve la primera IP en la lista de X-Forwarded-For. Asume que hay un proxy inverso adelante que ya saneo esta cabecera.
    """
    return request.headers.get("x-forwarded-for").split(",")[0]


def get_headers(request: Request) -> dict[str, str]:
    """
    Devuelve las cabeceras del cliente en la lista de cabeceras permitidas.
    """
    clean_headers = {
        key: value for key, value in request.headers.items() if key in ALLOWED_HEADERS
    }
    return clean_headers


def get_ip_detail(request: Request):
    """
    Consulta en la base de datos `mmdb` los datos detallados de la IP del cliente.
    """
    client_ip = get_plain_ip(request)
    manager = request.app.state.geoip
    data = get_json_mmdb(
        client_ip, city_reader=manager.reader("city"), asn_reader=manager.reader("asn")
    )
    data["rdap_url"] = rdap_store.rdap_url_for(client_ip)
    return data


def _epoch_to_iso(epoch: int) -> str:
    """
    Devuelve el timestamp ingresado en formato ISO-UTC.
    """
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Inicializa y almacena el administrador de las bases `mmdb`, la conexión a redis y activa el actualizador RDAP.
    """
    manager = GeoIPManager(
        {
            "asn": f"{GEOIP_PATH}/GeoLite2-ASN.mmdb",
            "city": f"{GEOIP_PATH}/GeoLite2-City.mmdb",
        }
    )
    await manager.start()
    app.state.geoip = manager
    app.state.redis = aioredis.from_url(REDIS_URL, decode_responses=True)

    await rdap_updater.start()
    try:
        yield
    finally:
        await manager.stop()
        await rdap_updater.stop()
        await app.state.redis.aclose()


app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def enforce_https(request: Request, call_next):
    """
    Rechaza las peticiones con IP privada (no protege contra spoofing) en X-Forwarded-For.
    Permite HTTP plano para clientes cli (lista blanca en `CLI_REGEX`) y en subdominios ipv4/6.
    Excluye `/ready` e `/info` del middleware.
    """
    user_agent = request.headers.get("user-agent", "")
    forwarded_proto = request.headers.get("x-forwarded-proto", "http")
    host = request.headers.get("host", "")
    client_ip = get_plain_ip(request)
    
    is_cli = bool(CLI_REGEX.search(user_agent)) or not user_agent
    response = None


    if request.url.path in EXCLUDED_MIDDLEWARE_PATHS:
        response = await call_next(request)

    elif not is_valid_ip(client_ip):
        response = JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "must be a public ip"},
        )

    elif forwarded_proto == "http":
        if is_cli or host in IP_HOSTS:
            response = await call_next(request)
        else:
            secure_url = f"https://{host}{request.url.path}"
            if request.url.query:
                secure_url += f"?{request.url.query}"
            response = RedirectResponse(
                url=secure_url, status_code=status.HTTP_301_MOVED_PERMANENTLY
            )

    elif forwarded_proto == "https":
        response = await call_next(request)

    log.info(
        '%s - "%s %s HTTP/%s" %s',
        client_ip if client_ip else request.client.host,
        request.method,
        request.headers.get("host", "-") + request.url.path,
        request.scope.get("http_version", "-"),
        response.status_code,
    )

    return response


@app.get("/")
@app.get("/ip")
async def root_dispatcher(request: Request):
    """
    Devuelve la IP del cliente en texto plano.
    """
    client_ip = get_plain_ip(request)
    return PlainTextResponse(content=f"{client_ip}\n")


@app.get("/ip/detail")
@app.get("/ip/details")
async def detail_dispatcher(request: Request):
    """
    Devuelve la consulta detallada de IP en JSON.
    """
    return JSONResponse(content=get_ip_detail(request))


@app.get("/client/headers")
async def headers_dispatcher(request: Request):
    """
    Devuelve las cabeceras del cliente en JSON.
    """
    return JSONResponse(content={"headers": get_headers(request)})


@app.get("/client/all")
@app.get("/ip/all")
@app.get("/all")
async def all_data(request: Request):
    """
    Unificado de la consulta IP detallada y cabeceras del cliente en único JSON.
    """
    data = get_ip_detail(request)
    data["headers"] = get_headers(request)
    return JSONResponse(content=data)


@app.get("/dns-leak/{test_id}")
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


@app.get("/info")
async def info(request: Request):
    """
    Devuelve metadata de las `mmdb`.
    """
    manager = getattr(request.app.state, "geoip", None)
    try:
        asn_last_update = manager.reader("asn").metadata().build_epoch
        city_last_update = manager.reader("city").metadata().build_epoch
    except (AttributeError, RuntimeError):
        return JSONResponse(
            {"status": "NOT READY"}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE
        )
    return JSONResponse(
        {
            "status": "OK",
            "asn_last_update": _epoch_to_iso(asn_last_update),
            "city_last_update": _epoch_to_iso(city_last_update),
        }
    )


@app.get("/ready")
async def health_check(request: Request):
    """
    Endpoint de salud. Verifica funcionalidad de las `mmdb`.
    """
    manager = getattr(request.app.state, "geoip", None)
    try:
        manager.reader("asn")
        manager.reader("city")
    except (AttributeError, RuntimeError):
        return JSONResponse(
            {"status": "NOT READY"}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE
        )
    return JSONResponse({"status": "OK"})
