import ipaddress
import logging

log = logging.getLogger("ip_utils")


def is_valid_ip(ip: str | None) -> bool:
    """
    Valida si una IP esta bien formada y que sea pública.
    """
    if not ip:
        return False
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


def ip_key(ip: str) -> tuple[int, ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """
    Clave de orden por IP: IPv4, IPv6.
    """
    addr = ipaddress.ip_address(ip)
    return addr.version, addr


def net_key(cidr: str) -> tuple[int, ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """
    Clave de orden por red: IPv4, IPv6.
    """
    net = ipaddress.ip_network(cidr, strict=False)
    return net.version, net
