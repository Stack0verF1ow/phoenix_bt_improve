from __future__ import annotations

import socket


def get_lan_ips() -> list[str]:
    """Get all non-loopback IPv4 addresses on this machine."""
    ips: set[str] = set()
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            addr = info[4][0]
            if addr and not addr.startswith("127."):
                ips.add(addr)
    except Exception:
        pass
    return sorted(ips)
