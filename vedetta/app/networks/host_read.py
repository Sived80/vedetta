"""The one reader of what the host says about its network: the default route and its gateway, from /proc/net/route. Files of the kernel only, no external command (it also works with BusyBox).
Functions over a file or its text, with no state of their own: the callers keep their caches (iface keeps the interface for the whole run)."""
from .. import procfs


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


def read_gateway(route_path: str) -> str | None:
    """The gateway of the first default route of the file; None if there is none or the file cannot be read."""
    try:
        for cols in procfs.table(route_path):
            if _is_default_route(cols):
                return _gateway_text(cols[2])
    except ValueError:         # a bad number (or a byte that is not ASCII) ends the reading with no answer
        pass
    return None


def _is_default_route(cols: list[str]) -> bool:
    """A line of /proc/net/route that is the default route and has the gateway flag (RTF_GATEWAY) set."""
    return len(cols) > 2 and cols[1] == "00000000" and bool(int(cols[3], 16) & 2)


def _gateway_text(hex_address: str) -> str:
    """Dotted address from the little-endian hexadecimal field of /proc/net/route."""
    raw = int(hex_address, 16).to_bytes(4, "little")
    return ".".join(str(b) for b in raw)
