import asyncio
import ipaddress
import logging
import os
import re
from logging.handlers import RotatingFileHandler

import dns.edns
import dns.exception
import dns.message
import dns.name
import dns.rcode
import dns.rdatatype
import dns.rrset
import redis.asyncio as aioredis

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
LOG_FILE = os.environ.get("LOG_FILE")
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
            log.exception("Error al transformar la query")
            return

        if not query.question:
            return

        q = query.question[0]
        q_name, q_type = q.name, q.rdtype

        log.debug(f"question: {q}")
        log.debug(f"question name: {q_name}")
        log.debug(f"question type: {q_type}")

        try:
            response = self._build_response(query, q_name, q_type)
        except dns.exception.FormError:
            log.exception("query mal formada")
            return

        log.debug(f"Destino: {addr};\nRespuesta: {response.to_text()}")
        self.transport.sendto(response.to_wire(), addr)
        ecs = self._get_ecs(query)
        ecs_cidr = None
        if ecs:
            ecs_cidr = ecs_to_cidr(ecs)

        token = self._extract_token(q_name)
        if token:
            resolver_ip = real_ip or addr[0]

            if not is_valid_ip(resolver_ip):
                # Las peticiones que reutilizan una conexión no vuelven a enviar PP.
                # Al descartar no se pierde datos, el 1er paquete de la conexión si posee PP.
                log.debug(f"Se descarta la IP {resolver_ip}. No posee header PP")
                return

            log.debug(f"real_ip: {real_ip}; addr[0]: {addr[0]}")
            asyncio.create_task(self._record(token, resolver_ip, q_type, ecs_cidr))

    def _get_ecs(self, query: dns.message.Message) -> dns.edns.ECSOption | None:
        """
        Extrae ECS de existir, caso contrario, devuelve None
        """
        if query.edns < 0:
            log.debug("ECS: None-1")
            return None
        for opt in query.options:
            log.debug(f"OPT: {opt}")
            if opt.otype == dns.edns.OptionType.ECS:
                log.debug(f"OPT ECS: {opt}")
                return opt
        log.debug("ECS: None-2")
        return None

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
        ecs = self._get_ecs(query)

        if ecs is not None:
            response.use_edns(
                0,
                payload=1232,
                options=[dns.edns.ECSOption(ecs.address, ecs.srclen, 0)],
            )

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
        self,
        token: str,
        resolver_ip: str,
        q_type: dns.rdatatype.RdataType,
        ecs_cidr: str | None,
    ) -> None:
        """
        Registra el token como clave en redis por TTL segundos. Se guarda la IP
        del resolver en texto plano para asegurar de-duplicación en resolvers
        repetidos.
        """
        key = f"dnsleak:{token}"
        log.debug(f"{token} - {resolver_ip} ({dns.rdatatype.to_text(q_type)})")
        log.info(f"{resolver_ip} ({dns.rdatatype.to_text(q_type)})")
        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.sadd(key, resolver_ip).expire(key, LEAK_KEY_TTL)
                if ecs_cidr:
                    pipe.sadd(f"{key}:ecs", f"{resolver_ip}|{ecs_cidr}").expire(
                        f"{key}:ecs", LEAK_KEY_TTL
                    )
                await pipe.execute()
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


def is_valid_ip(ip: str) -> bool:
    """
    Valida si una IP esta bien formada y que sea pública.
    """
    try:
        addr = ipaddress.ip_address(ip.strip())
        log.debug(f"Leyendo: {addr}")
    except ValueError:
        return False

    if not addr.is_global:
        return False

    if (
        addr.is_multicast
        or addr.is_loopback
        or addr.is_unspecified
        or addr.is_link_local
    ):
        return False

    return True


def ecs_to_cidr(opt: dns.edns.ECSOption) -> str | None:
    """
    De ser valido, transforma ECS en una network.
    """
    if opt.srclen == 0:
        return None
    try:
        net = ipaddress.ip_network(f"{opt.address}/{opt.srclen}", strict=False)
    except ValueError:
        return None
    return str(net) if is_valid_ip(str(net.network_address)) else None


async def main():
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if LOG_FILE:
        handlers[0].setLevel(logging.WARNING)
        handlers.append(
            RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024**2, backupCount=3)
        )

    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
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
