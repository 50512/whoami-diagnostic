from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from app.deps import get_ip_detail, get_plain_ip

router = APIRouter(tags=["ip"])


@router.get("/")
@router.get("/ip")
async def root_dispatcher(request: Request):
    """
    Devuelve la IP del cliente en texto plano.
    """
    return PlainTextResponse(content=f"{get_plain_ip(request)}\n")


@router.get("/ip/detail")
@router.get("/ip/details")
async def detail_dispatcher(request: Request):
    """
    Devuelve la consulta detallada de IP en JSON.
    """
    return JSONResponse(content=get_ip_detail(request, request.app.state.rdap_store))
