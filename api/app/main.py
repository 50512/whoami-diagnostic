from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, RedirectResponse, JSONResponse
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import os
import re

from app.lib.geoip_utils import GeoIPManager, get_json_mmdb

IP_HOSTS = [
    os.environ.get("IPV4_HOST"),
    os.environ.get("IPV6_HOST")
]

GEOIP_PATH = os.environ.get("GEOIP_PATH", "/var/opt/GeoIP")
CLI_REGEX = re.compile(r"(?i)(curl|wget|python|httpie|aria2)")


def get_plain_ip(request: Request) -> str:
    return request.headers.get("x-forwarded-for", "127.0.0.1").split(",")[0]


def _epoch_to_iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


@asynccontextmanager
async def lifespan(app: FastAPI):
    manager = GeoIPManager(
        {
            "asn": f"{GEOIP_PATH}/GeoLite2-ASN.mmdb",
            "city": f"{GEOIP_PATH}/GeoLite2-City.mmdb"
        }
    )
    await manager.start()
    app.state.geoip = manager
    try:
        yield
    finally:
        await manager.stop()


app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def enforce_https(request: Request, call_next):
    """
    Solo redirige a https cuando:
    - No es herramienta cli
    - No pertenece a los IP_HOSTS
    """
    user_agent = request.headers.get("user-agent", "")
    forwarded_proto = request.headers.get("x-forwarded-proto", "http")
    host = request.headers.get("host", "")
    
    is_cli = bool(CLI_REGEX.search(user_agent)) or not user_agent
    response = None
    
    if forwarded_proto == "https":
        response = await call_next(request)

    elif forwarded_proto == "http":
        if is_cli or host in IP_HOSTS:
            response = await call_next(request)
        else:
            secure_url = f"https://{host}{request.url.path}"
            if request.url.query:
                secure_url += f"?{request.url.query}"
            return RedirectResponse(url=secure_url, status_code=301)
    
    return response


@app.get("/")
@app.get("/ip")
async def root_dispatcher(request: Request):
    client_ip = get_plain_ip(request)
    return PlainTextResponse(content=f"{client_ip}\n")


@app.get("/ip/detail")
async def detail_dispatcher(request: Request):
    client_ip = get_plain_ip(request)
    manager = request.app.state.geoip
    data = get_json_mmdb(
        client_ip,
        city_reader=manager.reader("city"),
        asn_reader=manager.reader("asn")
    )
    return JSONResponse(content=data)


@app.get("/info")
async def info(request: Request):
    manager = getattr(request.app.state, "geoip", None)
    try:
        asn_last_update = manager.reader("asn").metadata().build_epoch
        city_last_update = manager.reader("city").metadata().build_epoch
    except (AttributeError, RuntimeError):
        return JSONResponse({
            "status": "NOT READY"
        }, status_code=503)
    return JSONResponse({
        "status": "OK",
        "asn_last_update": _epoch_to_iso(asn_last_update),
        "city_last_update": _epoch_to_iso(city_last_update)
    })


@app.get("/ready")
async def health_check(request: Request):
    manager = getattr(request.app.state, "geoip", None)
    try:
        asn = manager.reader("asn")
        city = manager.reader("city")
    except (AttributeError, RuntimeError):
        return JSONResponse({"status": "NOT READY"}, status_code=503)
    return JSONResponse({"status": "OK"})
