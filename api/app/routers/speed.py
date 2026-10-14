import logging
import os
import re
import secrets
from typing import Annotated

from fastapi import (APIRouter, Cookie, Depends, HTTPException, Query, Request,
                     Response, status)
from fastapi.responses import JSONResponse, StreamingResponse
from redis.asyncio import Redis

log = logging.getLogger("fastapi.speed")

router = APIRouter(prefix="/speed", tags=["speed"])

# Reutiliza el mismo bloque de 1MiB incompresible
CHUNK_SIZE = 1 << 20  # 1MiB
CHUNK = os.urandom(CHUNK_SIZE)
DEFAULT_SIZE = 40 << 20  # 40MiB

# Limite fijo de 500MiB por sesión
SESSION_BYTES = 500 << 20  # 500MiB
MAX_CONNS = 5

COOKIE_NAME = "speed_token"
TOKEN_BYTES = 24  # múltiplo de 3 para longitud exacta
TOKEN_LEN = TOKEN_BYTES * 4 // 3  # 32 chars por defecto
TOKEN_RE = re.compile(rf"^[A-Za-z0-9_-]{{{TOKEN_LEN}}}$")
TOKEN_KEY_PREFIX = "speed:tok:"
TTL_UNUSED = 30  # Máximo 30s si no se usa
TTL_AFTER_FIRST_USE = 60  # Se elimina 60s después del 1er uso
COOKIE_MAX_AGE = TTL_UNUSED + TTL_AFTER_FIRST_USE  # Tiempo máximo para la cookie

# Consume las conexiones de los tokens de manera atómica desde Redis.
# Retorna: {slots restantes, conns}
# SLOTS: >=0 slots | -1 agotado | -2 no existe/expiró
CONSUME_LUA = """
if redis.call('EXISTS', KEYS[1]) == 0 then return {-2, 0} end
local conns = tonumber(redis.call('HGET', KEYS[1], 'conns'))
local left = redis.call('HINCRBY', KEYS[1], ARGV[1], -1)
if left < 0 then return {-1, conns} end
if redis.call('HSETNX', KEYS[1], 'used', 1) == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[2])
end
local rest = redis.call('HMGET', KEYS[1], 'down', 'up')
if tonumber(rest[1]) <= 0 and tonumber(rest[2]) <= 0 then
  redis.call('DEL', KEYS[1])
end
return {left, conns}
"""


def _max_size(conns: int) -> int:
    """
    Tamaño máximo permitido por conexión.
    """
    return SESSION_BYTES // conns


def require_slot(direction: str):
    """
    Genera la dependencia que exige la cookie del speedtest,
    consume el slot de dirección (`down`|`up`). Devuelve el número
    de conexiones para el limite de la sesión.
    """

    async def dep(
        request: Request,
        token: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
    ) -> int:
        if not token:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing speed token")
        if not TOKEN_RE.fullmatch(token):
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, "invalid or expired token"
            )

        redis: Redis = request.app.state.redis
        key = TOKEN_KEY_PREFIX + token
        try:
            left, conns = await redis.eval(
                CONSUME_LUA, 1, key, direction, TTL_AFTER_FIRST_USE
            )
        except Exception:
            log.exception("Error al consumir el speedtest token")
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "speedtest unavailable"
            )

        if left == -2:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, "invalid or expired token"
            )
        if left == -1:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "token exhausted")
        return int(conns)

    return Depends(dep)


@router.post("/start")
async def speed_start(
    request: Request, conns: Annotated[int, Query(ge=1, le=MAX_CONNS)]
):
    """
    Crea el token de sesión con la cantidad de conexiones de bajada y subida.
    """
    token = secrets.token_urlsafe(TOKEN_BYTES)
    key = TOKEN_KEY_PREFIX + token
    redis: Redis = request.app.state.redis
    try:
        async with redis.pipeline(transaction=True) as pipe:
            await pipe.hset(
                key, mapping={"down": conns, "up": conns, "conns": conns}
            ).expire(key, TTL_UNUSED).execute()
    except Exception:
        log.exception("Error al crear el speedtest token")
        return JSONResponse(
            {"error": "speedtest_unavailable"},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    response = JSONResponse(
        {"conns": conns, "ttl": TTL_UNUSED, "max_size": _max_size(conns)}
    )

    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=COOKIE_MAX_AGE,
        path="/speed",
        httponly=True,
        secure=request.headers.get("x-forwarded-proto") == "https",
        samesite="strict",
    )
    return response


@router.get("/download")
async def speed_download(
    conns: Annotated[int, require_slot("down")],
    size: Annotated[int, Query(ge=1)] = DEFAULT_SIZE,
):
    """
    Genera un stream de `size` bytes, con un máximo en base a las conexiones permitidas.
    """
    limit = _max_size(conns)
    if size > limit:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"size exceeds session limit of {limit} bytes",
        )

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
async def speed_upload(request: Request, conns: Annotated[int, require_slot("up")]):
    """
    Sumidero que drena el stream completo de la subida. Todo el
    contenido es descartado.
    """
    limit = _max_size(conns)
    declared = request.headers.get("content-length", "")
    log.debug(f"Tamaño subido: {declared}")
    if declared.isdigit() and int(declared) > limit:
        return Response(status_code=status.HTTP_413_CONTENT_TOO_LARGE)

    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > limit:
            return Response(status_code=status.HTTP_413_CONTENT_TOO_LARGE)

    log.debug(f"Tamaño recibido: {received}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
