from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

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
