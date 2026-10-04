import ipaddress
import json

from app.lib.bootstrap.core import Entry, Source

QUAD9 = "Quad9"
CLOUDFLARE = "Cloudflare"


def parse_quad9(text: str) -> list[Entry]:
    """
    Parsea los outbound de Quad9:
    `{"last_updated": ..., "ipv4": [...], "ipv6": [...]}`.
    """
    doc = json.loads(text)
    cidrs = doc.get("ipv4", []) + doc.get("ipv6", [])
    return [(ipaddress.ip_network(c, strict=False), QUAD9) for c in cidrs]


def parse_cloudflare(text: str) -> list[Entry]:
    """
    Parsea `ips-v4` / `ips-v6` de Cloudflare: `text/plain`, un CIDR por línea.
    """
    return [
        (ipaddress.ip_network(line, strict=False), CLOUDFLARE)
        for line in (raw.strip() for raw in text.splitlines())
        if line and not line.startswith("#")
    ]


RESOLVER_SOURCES = {
    "quad9": Source(
        "https://quad9.net/ipranges/quad9-outbound-brief-latest.json", parse_quad9
    ),
    "cloudflare-ipv4": Source(
        "https://www.cloudflare.com/ips-v4", parse_cloudflare, ext="txt"
    ),
    "cloudflare-ipv6": Source(
        "https://www.cloudflare.com/ips-v6", parse_cloudflare, ext="txt"
    ),
}
