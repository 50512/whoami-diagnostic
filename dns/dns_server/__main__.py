import asyncio
import ipaddress
import logging
import os
import re

import dns.message
import dns.name
import dns.rcode
import dns.rdatatype
import dns.rrset
import redis.asyncio as aioredis

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
DNS_PORT = int(os.environ.get("DNS_PORT", "53"))
DNS_ZONE = os.environ.get("DNS_ZONE", "dns-leak.host.com")
ANSWER_IP = {"v4": "127.0.0.1", "v6": "::1"}
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

ZONE = dns.name.from_text(DNS_ZONE)
TTL = 60
LEAK_KEY_TTL = 60
TOKEN_RE = re.compile(r"^[a-f0-9]{32}$")

_PROXY_PROTOCOL_V2_SIGN = b"\r\n\r\n\x00\r\nQUIT\n"

log = logging.getLogger("dns")


class LeakResolverProtocol(asyncio.DatagramProtocol):
    """
    Clase del resolver de las fugas DNS.
    Administra todo el ciclo de vida de las peticiones realizadas,
    las respuestas a enviar y almacenar los tokens validos en redis.
    """

    def __init__(self, redis: aioredis.Redis):
        """
        Inicializa con la instancia de redis donde guardar las peticiones
        a tokens válidos.
        """
        self.redis = redis
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data: bytes, addr):
        """
        Intenta convertir el payload en una petición DNS válida.
        De lograrlo, procesa la petición exclusivamente a la zona
        asignada, extrae el token y de ser válido, lo almacena en redis.
        """
        real_ip, payload = strip_proxy_protocol_v2(data)
        log.debug(f"real_ip: {real_ip}; payload: {payload}")

        try:
            query = dns.message.from_wire(payload)
            log.debug(f"query: {query}")
        except Exception:
            return

        if not query.question:
            return

        q = query.question[0]
        q_name, q_type = q.name, q.rdtype

        log.debug(f"question: {q}")
        log.debug(f"question name: {q_name}")
        log.debug(f"question type: {q_type}")

        response = self._build_response(query, q_name, q_type)
        log.debug(f"Destino: {addr};\nRespuesta: {response.to_text()}")
        self.transport.sendto(response.to_wire(), addr)

        token = self._extract_token(q_name)
        if token:
            resolver_ip = real_ip or addr[0]
            log.debug(f"real_ip: {real_ip}; addr[0]: {addr[0]}")
            asyncio.create_task(self._record(token, resolver_ip, q_type))

    def _extract_token(self, q_name: dns.name.Name) -> str | None:
        """
        Extrae el token primario (32 caracteres alfanuméricos) que se usa como
        identificador de test/usuario de los tokens de petición. Devuelve el
        token primario de existir.
        """
        if not q_name.is_subdomain(ZONE):
            return None
        rel = q_name.relativize(ZONE)
        if rel == dns.name.empty:
            return None
        token = rel.labels[-1].decode("ascii", "ignore").lower()
        return token if TOKEN_RE.match(token) else None

    def _build_response(
        self,
        query: dns.message.Message,
        q_name: dns.name.Name,
        q_type: dns.rdatatype.RdataType,
    ) -> dns.message.Message:
        """
        Construye la respuesta para el cliente DNS. Solo envía respuesta
        válida si el subdominio pertenece a la zona.
        """
        response = dns.message.make_response(query)
        if not q_name.is_subdomain(ZONE):
            response.set_rcode(dns.rcode.REFUSED)
            log.debug(f"Respuesta nula para {q_name}({dns.rdatatype.to_text(q_type)})")
            return response
        if q_type == dns.rdatatype.A:
            response.answer.append(
                dns.rrset.from_text(q_name, TTL, "IN", "A", ANSWER_IP["v4"])
            )
        elif q_type == dns.rdatatype.AAAA:
            response.answer.append(
                dns.rrset.from_text(q_name, TTL, "IN", "AAAA", ANSWER_IP["v6"])
            )
        return response

    async def _record(
        self, token: str, resolver_ip: str, q_type: dns.rdatatype.RdataType
    ) -> None:
        """
        Registra el token como clave en redis por TTL segundos. Se guarda la IP
        del resolver en texto plano para asegurar de-duplicación en resolvers
        repetidos.
        """
        key = f"dnsleak:{token}"
        log.info(f"{token} - {resolver_ip} ({dns.rdatatype.to_text(q_type)})")
        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                await pipe.sadd(key, resolver_ip).expire(key, LEAK_KEY_TTL).execute()
        except Exception:
            log.exception("dns: Error al guardar el leak")


def strip_proxy_protocol_v2(data: bytes) -> tuple[str | None, bytes]:
    """
    Extrae posible cabecera de proxyProtocolV2 de la data.
    En caso haber cabecera de PP, se separa el fragmento IP
    del fragmento payload. En caso no encontrarse, se devuelve
    la data tal cual.
    """

    # Data menor que PP + metadata o la firma de PPv2 no esta en la cabecera de 12 bytes
    if len(data) < 16 or data[:12] != _PROXY_PROTOCOL_V2_SIGN:
        return None, data

    # Versión de PP diferente de 2
    ver_cmd = data[12]
    if ver_cmd >> 4 != 0x2:
        return None, data

    # Identificar longitud de dirección del PP. Si esta truncado, se envía data tal cual.
    addr_len = int.from_bytes(data[14:16], "big")
    if len(data) < 16 + addr_len:
        return None, data

    # Separar bloque PP de payload
    block = data[16 : 16 + addr_len]
    payload = data[16 + addr_len :]

    # Ignorar si el comando es diferente de PROXY (0x1)
    if ver_cmd & 0x0F != 0x1:
        return None, payload

    fam = data[13]
    af = fam >> 4
    try:
        # Identifica familia y traduce a IPv4/6 en base a familia y longitud
        if af == 0x1 and len(block) >= 12:
            src_ip = str(ipaddress.IPv4Address(block[0:4]))
        elif af == 0x2 and len(block) >= 36:
            src_ip = str(ipaddress.IPv6Address(block[0:16]))
        else:
            src_ip = None
    except ValueError:
        log.exception("Error en la traducción de la IP a string.")
        src_ip = None
    return src_ip, payload


async def main():
    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    loop = asyncio.get_running_loop()

    transport, _ = await loop.create_datagram_endpoint(
        lambda: LeakResolverProtocol(redis), local_addr=("0.0.0.0", DNS_PORT)
    )
    log.info(f"DNS leak server activo en:{DNS_PORT}/udp | zona {DNS_ZONE}")

    try:
        await asyncio.Event().wait()
    finally:
        transport.close()
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
