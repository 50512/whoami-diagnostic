from datetime import datetime, timezone

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

router = APIRouter(tags=["meta"])


def _epoch_to_iso(epoch: int) -> str:
    """
    Devuelve el timestamp ingresado en formato ISO-UTC.
    """
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


@router.get("/info")
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


@router.get("/ready")
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
