import logging
import os

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import StreamingResponse

log = logging.getLogger("fastapi.speed")

router = APIRouter(prefix="/speed", tags=["speed"])

CHUNK_SIZE = 1 << 20  # 1MiB
CHUNK = os.urandom(CHUNK_SIZE)
MAX_SIZE = 500 << 20  # 500MiB
DEFAULT_SIZE = 40 << 20  # 40MiB


@router.get("/download")
async def speed_download(size: int = Query(default=DEFAULT_SIZE, ge=1, le=MAX_SIZE)):
    """
    Genera un archivo entre 1B a 500MiB (basado en bloques de 1MiB) para descarga.
    """

    async def gen():
        remaining = size
        while remaining >= CHUNK_SIZE:
            yield CHUNK
            remaining -= CHUNK_SIZE
        if remaining:
            yield CHUNK[:remaining]

    return StreamingResponse(
        gen(),
        media_type="application/octet-stream",
        headers={"Content-Length": str(size)},
    )


@router.post("/upload")
async def speed_upload(request: Request):
    """
    Sumidero que drena el stream completo de la subida. Todo el
    contenido es descartado.
    """
    declared = request.headers.get("content-length", "")
    log.debug(f"Tamaño subido: {declared}")
    if declared.isdigit() and int(declared) > MAX_SIZE:
        return Response(status_code=status.HTTP_413_CONTENT_TOO_LARGE)

    async for _ in request.stream():
        pass

    return Response(status_code=status.HTTP_204_NO_CONTENT)
