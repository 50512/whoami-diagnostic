import asyncio
import ipaddress
import json
import logging
import os
import re
import time

import dns.message
import dns.name
import dns.rcode
import dns.rdatatype
import dns.rrset
import redis.asyncio as aioredis

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
    def __init__(self, redis: aioredis.Redis):
        self.redis = redis
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data: bytes, addr):
        real_ip, payload = strip_proxy_protocol_v2(data)

        try:
            query = dns.message.from_wire(payload)
        except Exception:
            return

        if not query.question:
            return

        q = query.question[0]
        q_name, q_type = q.name, q.rdtype

        response = self._build_response(query, q_name, q_type)
        self.transport.sendto(response.to_wire(), addr)

        token = self._extract_token(q_name)
        if token:
            resolver_ip = real_ip or addr[0]
            asyncio.create_task(self._record(token, resolver_ip, q_type))

    def _extract_token(self, q_name: dns.name.Name) -> str | None:
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
        response = dns.message.make_response(query)
        if not q_name.is_subdomain(ZONE):
            return response.set_rcode(dns.rcode.REFUSED)
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
        key = f"dnsleak:{token}"
        print(f"dns: {token} - {resolver_ip} ({dns.rdatatype.to_text(q_type)})")
        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                await pipe.sadd(key, resolver_ip).expire(key, LEAK_KEY_TTL).execute()
        except Exception as e:
            log.error(f"dns: Error al guardar el leak: {e}")


def strip_proxy_protocol_v2(data: bytes) -> tuple[str | None, bytes]:
    if len(data) < 16 or data[:12] != _PROXY_PROTOCOL_V2_SIGN:
        return None, data

    ver_cmd = data[12]
    if ver_cmd >> 4 != 0x2:
        return None, data

    fam = data[13]
    addr_len = int.from_bytes(data[14:16], "big")
    if len(data) < 16 + addr_len:
        return None, data

    block = data[16 : 16 + addr_len]
    payload = data[16 + addr_len :]

    if ver_cmd & 0x0F != 0x1:
        return None, payload

    af = fam >> 4
    try:
        if af == 0x1 and len(block) >= 12:
            src_ip = str(ipaddress.IPv4Address(block[0:4]))
        elif af == 0x2 and len(block) >= 36:
            src_ip = str(ipaddress.IPv6Address(block[0:16]))
        else:
            src_ip = None
    except ValueError:
        src_ip = None
    return src_ip, payload


async def main():
    redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    loop = asyncio.get_running_loop()

    transport, _ = await loop.create_datagram_endpoint(
        lambda: LeakResolverProtocol(redis), local_addr=("0.0.0.0", DNS_PORT)
    )
    print(f"DNS leak server activo en:{DNS_PORT}/udp | zona {DNS_ZONE}")

    try:
        await asyncio.Event().wait()
    finally:
        transport.close()
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
