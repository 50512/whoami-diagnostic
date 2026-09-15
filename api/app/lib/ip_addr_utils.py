import ipaddress
import logging

log = logging.getLogger("ip_utils")


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
