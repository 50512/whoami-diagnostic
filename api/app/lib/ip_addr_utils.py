import ipaddress


def is_valid_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip.strip())
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
