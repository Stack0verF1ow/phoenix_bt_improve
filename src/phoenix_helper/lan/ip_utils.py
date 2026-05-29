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


def probe_ips(hosts: list[str], port: int, timeout: float = 3.0) -> str | None:
    """Try TCP connect to each host:port, return the first reachable one."""
    for host in hosts:
        try:
            sock = socket.create_connection((host, port), timeout=timeout)
            sock.close()
            return host
        except (OSError, socket.timeout):
            continue
    return None
