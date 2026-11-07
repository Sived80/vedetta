"""The one reader of what the host says about its network: the default route of /proc/net/route. Files of the kernel only, no external command (it also works with BusyBox).
Pure functions over the text of the files; the callers keep their own caches (iface keeps the interface for the whole run)."""


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
