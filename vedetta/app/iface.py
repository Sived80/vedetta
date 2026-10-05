"""LAN network interface: from VEDETTA_IFACE, otherwise from the default
routing (/proc/net/route, no external command: it also works with BusyBox).
Fallback "eth0" (the current LXC container)."""
import os
from functools import lru_cache

_ROUTE_FILE = "/proc/net/route"
FALLBACK = "eth0"


def parse_default_route(text: str) -> str | None:
    """Interface of the route with destination 0.0.0.0/0 and lowest metric."""
    best: tuple[int, str] | None = None
    for line in text.splitlines()[1:]:
        f = line.split()
        if len(f) < 8 or f[1] != "00000000" or f[7] != "00000000":
            continue
        try:
            metric = int(f[6])
        except ValueError:
            metric = 0
        if best is None or metric < best[0]:
            best = (metric, f[0])
    return best[1] if best else None


@lru_cache(maxsize=1)
def lan_iface() -> str:
    forced = os.environ.get("VEDETTA_IFACE", "").strip()
    if forced:
        return forced
    try:
        with open(_ROUTE_FILE, encoding="ascii", errors="replace") as fh:
            found = parse_default_route(fh.read())
    except OSError:
        found = None
    return found or FALLBACK
