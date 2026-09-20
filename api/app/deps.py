from fastapi import Request

from app.lib.geoip_utils import get_json_mmdb
from app.lib.rdap_bootstrap import BootstrapStore

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


def get_plain_ip(request: Request) -> str | None:
    """
    Devuelve la primera IP en la lista de X-Forwarded-For. Asume que hay un proxy inverso adelante que ya saneo esta cabecera.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0]
    return None


def get_headers(request: Request) -> dict[str, str]:
    """
    Devuelve las cabeceras del cliente en la lista de cabeceras permitidas.
    """
    clean_headers = {
        key: value for key, value in request.headers.items() if key in ALLOWED_HEADERS
    }
    return clean_headers


def get_ip_detail(request: Request, rdap_store: BootstrapStore) -> dict[str, any]:
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
