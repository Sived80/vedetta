"""probe_web: moved out of probe.py (see tools/split_module.py)."""


from .scan_common import port_number


def _web_open(scanned_ports: list[dict]) -> bool | None:
    """True if an open port really serves a page for people, False if the ports were checked and none does,
    None if they were never checked (devices analysed before this check existed)."""
    checked = [p for p in scanned_ports if "web_ui" in p]
    if not checked:
        return None
    return any(p["web_ui"] for p in checked)


def _web_url(ip: str, port: int, scanned_ports: list[dict]) -> str:
    """Address of the "open web interface" button: the device's own port when it serves a real page, otherwise the
    best port that does (80 and 443 first), with https where the page needs it."""
    pages = _verified_pages(scanned_ports)
    if not pages:
        return _unverified_url(ip, port, scanned_ports)
    chosen = next((x for x in pages if x[1] == port), None) or min(pages, key=lambda x: (x[1] not in (80, 443), x[1]))
    entry, number = chosen
    return f"{entry.get('web_scheme') or 'http'}://{ip}:{number}"


def _verified_pages(scanned_ports: list[dict]) -> list[tuple[dict, int]]:
    """(entry, port number) of the ports that really serve a page."""
    pages = [(p, port_number(p)) for p in scanned_ports if p.get("web_ui")]
    return [(p, n) for p, n in pages if n is not None]


def _unverified_url(ip: str, port: int, scanned_ports: list[dict]) -> str:
    """No page was verified. The port the device was added with is kept if it is open (or if nothing is known about the ports);
    if the scan shows it is closed but another open port is a web service (Glances on 61208), the button points there."""
    numbers = {port_number(p) for p in scanned_ports} - {None}
    web = _confirmed_web_ports(scanned_ports)
    if not numbers or port in numbers or not web:
        return f"http://{ip}:{port}"
    n = min(web, key=lambda x: (x not in (80, 443), x))
    entry = next(p for p in scanned_ports if port_number(p) == n)
    return f"{'https' if 'https' in str(entry.get('label', '')).lower() else 'http'}://{ip}:{n}"


def _confirmed_web_ports(scanned_ports: list[dict]) -> list[int]:
    """Numbers of the open ports whose service is a confirmed web service, ascending."""
    numbers = (port_number(p) for p in scanned_ports if p.get("category") == "web" and p.get("confirmed"))
    return sorted(n for n in numbers if n)
