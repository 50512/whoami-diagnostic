from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from app.deps import get_headers, get_ip_detail

router = APIRouter(tags=["client"])


@router.get("/client/headers")
async def headers_dispatcher(request: Request):
    """
    Devuelve las cabeceras del cliente en JSON.
    """
    return JSONResponse(content={"headers": get_headers(request)})


@router.get("/client/all")
@router.get("/ip/all")
@router.get("/all")
async def all_data(request: Request):
    """
    Unificado de la consulta IP detallada y cabeceras del cliente en único JSON.
    """
    data = get_ip_detail(request, request.app.state.rdap_store)
    data["headers"] = get_headers(request)
    return JSONResponse(content=data)


@router.get("/all.txt")
async def text_plain_data(request: Request):
    data = get_ip_detail(request, request.app.state.rdap_store)
    data["headers"] = get_headers(request)

    attributions = []
    if data.get("attributions", False):
        for attr in data["attributions"]:
            attributions.append(data["attributions"][attr]["text"])

    headers = []
    for header in data["headers"]:
        headers.append(f"{header}: {data["headers"].get(header, "-")}")

    res = f"""\
# Diagnostic (txt)
## IP info
IP: {data.get("ip", "-")}
ASN: AS{data.get("asn", "-")} - {data.get("asn_org", "")}
CIDR: {data.get("cidr", "-")}
GEO: {data["geolocation"]["country"].get("name", "-")}/{data["geolocation"].get("region", "-")}/{data["geolocation"].get("city", "-")}
LOCATION: {data["location"].get("latitude", "-")}, {data["location"].get("longitude", "-")} ±{data["location"].get("accuracy_radius", "-")}Km
TIMEZONE: {data["location"].get("timezone", "-")}

## RDAP info
RDAP URL: {data.get("rdap_url", "-")}

## Client headers
{"\n".join(headers)}

ATTRIBUTIONS: {"|".join(attributions)}
"""

    return PlainTextResponse(content=res)
