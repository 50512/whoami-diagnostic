import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse

from app.lib.geoip_utils import GeoIPManager, get_json_mmdb
from app.lib.ip_addr_utils import is_valid_ip
from app.lib.rdap_bootstrap import BootstrapStore, BootstrapUpdater

IP_HOSTS = [os.environ.get("IPV4_HOST"), os.environ.get("IPV6_HOST")]

GEOIP_PATH = os.environ.get("GEOIP_PATH", "/var/opt/GeoIP")
CLI_REGEX = re.compile(r"(?i)(curl|wget|python|httpie|aria2)")

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


def get_plain_ip(request: Request) -> str:
    return request.headers.get("x-forwarded-for", "127.0.0.1").split(",")[0]


def get_headers(request: Request) -> dict[str, str]:
    clean_headers = {
        key: value for key, value in request.headers.items() if key in ALLOWED_HEADERS
    }

    return clean_headers


def get_ip_detail(request: Request):
    client_ip = get_plain_ip(request)
    manager = request.app.state.geoip
    data = get_json_mmdb(
        client_ip, city_reader=manager.reader("city"), asn_reader=manager.reader("asn")
    )
    data["rdap_url"] = rdap_store.rdap_url_for(client_ip)
    return data


def _epoch_to_iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


@asynccontextmanager
async def lifespan(app: FastAPI):
    manager = GeoIPManager(
        {
            "asn": f"{GEOIP_PATH}/GeoLite2-ASN.mmdb",
            "city": f"{GEOIP_PATH}/GeoLite2-City.mmdb",
        }
    )
    await manager.start()
    app.state.geoip = manager

    await rdap_updater.start()
    try:
        yield
    finally:
        await manager.stop()
        await rdap_updater.stop()


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

    if not is_valid_ip(get_plain_ip(request)):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "must be a public ip"},
        )

    is_cli = bool(CLI_REGEX.search(user_agent)) or not user_agent
    response = None

    if forwarded_proto == "http":
        if is_cli or host in IP_HOSTS:
            response = await call_next(request)
        else:
            secure_url = f"https://{host}{request.url.path}"
            if request.url.query:
                secure_url += f"?{request.url.query}"
            return RedirectResponse(url=secure_url, status_code=301)

    elif forwarded_proto == "https":
        response = await call_next(request)

    return response


@app.get("/")
@app.get("/ip")
async def root_dispatcher(request: Request):
    client_ip = get_plain_ip(request)
    return PlainTextResponse(content=f"{client_ip}\n")


@app.get("/ip/detail")
@app.get("/ip/details")
async def detail_dispatcher(request: Request):
    return JSONResponse(content=get_ip_detail(request))


@app.get("/client/headers")
async def headers_dispatcher(request: Request):
    return JSONResponse(content={"headers": get_headers(request)})


@app.get("/client/all")
@app.get("/ip/all")
@app.get("/all")
async def all_data(request: Request):
    data = get_ip_detail(request)
    data["headers"] = get_headers(request)
    return JSONResponse(content=data)


@app.get("/info")
async def info(request: Request):
    manager = getattr(request.app.state, "geoip", None)
    try:
        asn_last_update = manager.reader("asn").metadata().build_epoch
        city_last_update = manager.reader("city").metadata().build_epoch
    except (AttributeError, RuntimeError):
        return JSONResponse({"status": "NOT READY"}, status_code=503)
    return JSONResponse(
        {
            "status": "OK",
            "asn_last_update": _epoch_to_iso(asn_last_update),
            "city_last_update": _epoch_to_iso(city_last_update),
        }
    )


@app.get("/ready")
async def health_check(request: Request):
    manager = getattr(request.app.state, "geoip", None)
    try:
        manager.reader("asn")
        manager.reader("city")
    except (AttributeError, RuntimeError):
        return JSONResponse({"status": "NOT READY"}, status_code=503)
    return JSONResponse({"status": "OK"})
