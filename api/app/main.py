import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

import redis.asyncio as aioredis
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse, RedirectResponse

from app.deps import get_plain_ip
from app.lib.geoip_utils import GeoIPManager
from app.lib.ip_addr_utils import is_valid_ip
from app.lib.rdap_bootstrap import BootstrapStore, BootstrapUpdater
from app.routers import client, dns_leak, ip, meta, speed

ENABLE_DOCS = str(os.getenv("ENABLE_DOCS")).lower() in ("1", "on", "enable", "true")

IP_HOSTS = [os.environ.get("IPV4_HOST"), os.environ.get("IPV6_HOST")]
EXCLUDED_MIDDLEWARE_PATHS = ["/ready", "/info"]
CLI_REGEX = re.compile(r"(?i)(curl|wget|python|httpie|aria2)")

GEOIP_PATH = os.environ.get("GEOIP_PATH", "/var/opt/GeoIP")
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
log = logging.getLogger("fastapi.access")
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


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
    rdap_store = BootstrapStore()
    app.state.rdap_store = rdap_store
    rdap_updater = BootstrapUpdater(rdap_store, data_dir=Path("/data/rdap-bootstrap"))

    await rdap_updater.start()
    try:
        yield
    finally:
        await manager.stop()
        await rdap_updater.stop()
        await app.state.redis.aclose()


app = FastAPI(
    lifespan=lifespan,
    docs_url="/docs" if ENABLE_DOCS else None,
    redoc_url="/redoc" if ENABLE_DOCS else None,
    openapi_url="/openapi.json" if ENABLE_DOCS else None,
)
app.include_router(ip.router)
app.include_router(client.router)
app.include_router(dns_leak.router)
app.include_router(meta.router)
app.include_router(speed.router)


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
