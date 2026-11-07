"""LAN network interface: from VEDETTA_IFACE, otherwise from the default
routing (/proc/net/route, no external command: it also works with BusyBox).
Fallback "eth0" (the current LXC container).

The name ends up in commands (arp-scan, nmap, ip) and in a path (/sys/class/net/<name>): one written in the options is used only
if it looks like an interface name (letters, digits, "_", ".", "-", at most 15 characters, the limit of Linux, not starting with "-");
otherwise it is said in the log and the interface of the default route is used."""
import os
import re
from functools import lru_cache

from .networks.host_read import parse_default_route

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,14}")


def valid_name(name: str) -> bool:
    return bool(_NAME.fullmatch(name)) and name not in (".", "..")

_ROUTE_FILE = "/proc/net/route"
FALLBACK = "eth0"


@lru_cache(maxsize=1)
def lan_iface() -> str:
    forced = os.environ.get("VEDETTA_IFACE", "").strip()
    if forced and valid_name(forced):
        return forced
    if forced:
        from .applog import logger
        logger.warning("Opzione «interface» ignorata: %r non e' un nome di interfaccia; uso quella della rotta predefinita", forced[:40])
    try:
        with open(_ROUTE_FILE, encoding="ascii", errors="replace") as fh:
            found = parse_default_route(fh.read())
    except OSError:
        found = None
    return found or FALLBACK
