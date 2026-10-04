import ipaddress
import json

from app.lib.bootstrap.core import Entry, PrefixStore, Source


def parse_iana(text: str) -> list[Entry]:
    """
    Parsea un doc bootstrap de la IANA a entradas `(net, base_url)`.
    """
    entries: list[Entry] = []
    for patterns, servers in (e[:2] for e in json.loads(text).get("services", [])):
        if not servers:
            continue
        base = servers[0].rstrip("/") + "/"
        entries.extend((ipaddress.ip_network(cidr), base) for cidr in patterns)
    return entries


IANA_SOURCES = {
    "ipv4": Source("https://data.iana.org/rdap/ipv4.json", parse_iana),
    "ipv6": Source("https://data.iana.org/rdap/ipv6.json", parse_iana),
}


def rdap_url_for(store: PrefixStore, ip: str) -> str | None:
    """
    Devuelve la URL del servidor RDAP correspondiente a la IP.
    """
    base = store.lookup(ip)
    return f"{base}ip/{ip}" if base else None
