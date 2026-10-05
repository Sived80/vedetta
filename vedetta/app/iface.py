"""Interfaccia di rete della LAN: da VEDETTA_IFACE, altrimenti dall'instradamento
predefinito (/proc/net/route, nessun comando esterno: funziona anche con BusyBox).
Ripiego "eth0" (il container LXC attuale)."""
import os
from functools import lru_cache

_ROUTE_FILE = "/proc/net/route"
FALLBACK = "eth0"


def parse_default_route(text: str) -> str | None:
    """Interfaccia della rotta con destinazione 0.0.0.0/0 e metrica minore."""
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
