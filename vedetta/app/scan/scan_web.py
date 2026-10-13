"""scan_web: moved out of scanner.py (see tools/split_module.py)."""
import asyncio
from .scan_cert import cert_subject
from ..formatters import is_useless_title
import re
import ssl
import contextlib
from .scan_common import NO_REQUEST_PORTS, can_be_web


WEB_SERVICE_NAMES = {"http", "https", "http-alt", "http-proxy", "https-alt", "www", "sun-answerbook"}


EPHEMERAL_PORT_START = 49152  # IANA dynamic/private range: never a stable service


async def _https_get(ip: str, port: int, timeout: float) -> tuple[bytes, str | None] | None:
    """GET over TLS without verification (it is a home device with its own certificate): response
    and certificate subject."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, port, ssl=ctx), timeout=timeout)
        subject = None
        sslobj = writer.get_extra_info("ssl_object")
        if sslobj:
            der = sslobj.getpeercert(binary_form=True)
            subject = cert_subject(der) if der else None
        writer.write(f"GET / HTTP/1.0\r\nHost: {ip}\r\n\r\n".encode())
        await writer.drain()
        data = await asyncio.wait_for(reader.read(65536), timeout=timeout)
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
        return data, subject
    except Exception:
        return None


async def _close_writer(writer) -> None:
    """Closes the connection; a failure while closing is not an error."""
    writer.close()
    with contextlib.suppress(Exception):
        await writer.wait_closed()


async def _read_rest(reader, data: bytes) -> bytes:
    """Many small servers send the headers and the page in separate packets: keep reading (briefly) until the
    connection closes, otherwise a real page looks empty."""
    while data.startswith(b"HTTP/") and len(data) < 65536:
        try:
            chunk = await asyncio.wait_for(reader.read(65536 - len(data)), timeout=0.4)
        except asyncio.TimeoutError:
            break
        if not chunk:
            break
        data += chunk
    return data


async def _plain_get(ip: str, port: int, timeout: float) -> bytes:
    """One plain GET on the port: everything that arrived (cap 64KB), the connection closed."""
    reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=timeout)
    writer.write(f"GET / HTTP/1.0\r\nHost: {ip}\r\n\r\n".encode())
    await writer.drain()
    data = await asyncio.wait_for(reader.read(65536), timeout=timeout)
    data = await _read_rest(reader, data)
    await _close_writer(writer)
    return data


def _plain_is_enough(data: bytes) -> bool:
    """True if the plain answer is a good HTTP one: a 2xx, or a 3xx that does not send to https."""
    head0 = data.partition(b"\r\n\r\n")[0].lower()
    return data.startswith(b"HTTP/") and (data[9:10] == b"2" or (data[9:10] == b"3" and b"location: https:" not in head0))


async def _plain_or_tls(ip: str, port: int, timeout: float, data: bytes) -> tuple[bytes, str | None, bool] | None:
    """(answer, certificate subject, over TLS?) to use, or None if the port does not speak HTTP. A TLS port answers plain text badly
    (no HTTP, or a 4xx/5xx error): we retry over TLS, which also provides page, title and certificate."""
    if _plain_is_enough(data):
        return data, None, False
    tls = await _https_get(ip, port, max(timeout, 4.0))
    if tls and tls[0].startswith(b"HTTP/"):
        data, tls_subject = tls
        return data, tls_subject, True
    if not data.startswith(b"HTTP/"):
        return None
    return data, None, False


def _describe_response(data: bytes, tls_subject: str | None, used_tls: bool) -> dict:
    """The response is already here: besides the size we read, almost
    for free, the Server header and the page title. They say what
    is really running on that port (e.g. "pve-api-daemon" = Proxmox) much
    better than the MAC prefix of the network card alone."""
    head, _, body = data.partition(b"\r\n\r\n")
    server = re.search(rb"\r\nServer:[ \t]*([^\r\n]+)", head, re.IGNORECASE)
    title = re.search(rb"<title[^>]*>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
    status_line = re.match(rb"HTTP/[0-9.]+ (\d{3})", data)
    status = int(status_line.group(1)) if status_line else None
    page_title = " ".join(title.group(1).decode("utf-8", "ignore").split())[:120] if title else None
    return {
        "tls_subject": tls_subject,
        "size": len(data),
        "server": server.group(1).decode("latin-1").strip()[:120] if server else None,
        "title": page_title,
        "status": status,
        "scheme": "https" if used_tls else "http",
        "usable": is_web_ui(status, page_title, len(body)),
    }


async def _confirm_http_port(ip: str, port: int, timeout: float = 1.5) -> dict | None:
    """Direct, minimal proof (a single GET) that an HTTP server really
    answers on that port, instead of guessing from the service name or the
    port number. Used in deep_scan/probe_and_classify, which do not run
    -sV/--script (too slow there, see deep_scan): without this check, on
    a host with many open ports but none recognized by name (e.g. mqtt,
    llmnr, non-standard internal services) the old heuristic "first port not
    obviously non-web" still ended up guessing wrong (verified: on a
    Home Assistant VM with 14 open ports, the real 8123 lost against lower
    ports like 1884, never recognized but not excludable a priori
    without an endless list of exceptions).

    Returns how many response bytes arrived (cap 64KB, no need to
    download everything) instead of a simple yes/no: if several ports of the same
    host all turn out to be real HTTP (rare but it happened: a main app +
    a lighter internal console), there must be a way to choose which one to
    propose. None if the port does not speak HTTP."""
    if port in NO_REQUEST_PORTS:
        return None            # a printer prints what it is sent
    try:
        data = await _plain_get(ip, port, timeout)
        answer = await _plain_or_tls(ip, port, timeout, data)
        if answer is None:
            return None
        return _describe_response(*answer)
    except Exception:
        return None


def is_web_ui(status: int | None, title: str | None, body_len: int) -> bool:
    """True if what answers on `/` is a page a person can open: a normal page (2xx/3xx with a title or some content),
    or a login that asks for credentials (401). A 403 is a refusal, not a login: the page is not for people.
    A 404/400/5xx, an empty answer or a few bytes of API output (the REST service of a TV, the control port of a streaming stick, the UPnP
    port of a speaker that answers 403) is not a web interface, even if a web server is running."""
    if status is None:
        return False
    if status == 401:
        return True
    if 300 <= status < 400:
        return True
    if 200 <= status < 300:
        return bool(title and not is_useless_title(title)) or body_len >= 60
    return False


def _mark_port(p: dict, found: dict | None) -> None:
    """Writes in the port the result of its HTTP check (None: no HTTP server answered)."""
    p["http_body_size"] = found["size"] if found else None
    p["web_ui"] = bool(found and found["usable"])
    p["web_scheme"] = found["scheme"] if found else "http"
    if found:
        p["http_server"] = found["server"]
        p["http_page_title"] = found["title"]
        if found.get("tls_subject"):
            p["tls_subject"] = found["tls_subject"]


async def _confirm_http_ports(ip: str, ports: list[dict]) -> None:
    """Marks in place (key 'http_body_size') every stable port on which
    an HTTP server really answers. All ports in parallel: the cost is
    that of the slowest single check (max ~1.5s), not the sum."""
    # Also the ports on which nmap already read a title: the GET is needed to read
    # the Server header, which nmap does not give us.
    stable_ports = [p for p in ports if p["port"] < EPHEMERAL_PORT_START]
    if not stable_ports:
        return
    asked = [p for p in stable_ports if can_be_web(p)]       # only a port that can be a web server gets the request: a printer prints what it is sent, a controller could take it as a command
    results = await asyncio.gather(*(_confirm_http_port(ip, p["port"]) for p in asked))
    found_on = {id(p): found for p, found in zip(asked, results)}
    for p in stable_ports:
        _mark_port(p, found_on.get(id(p)))


def _confirmed_web_port(stable_ports: list[dict]) -> int | None:
    """The port that really answered over HTTP, or None. 80 and 443 win among several; otherwise the one with the most content."""
    # Strongest proof of all: nmap really obtained an HTML page with a
    # title from that port, not just a guess from the service name.
    # It solves the case of a Home Assistant VM where 80 was open (for
    # whatever other reason) but serving nothing real, while the real
    # interface was on 8123 - the "always prefer 80" rule below
    # would pick it first anyway, by convention, discarding the right one.
    # http_body_size comes from _confirm_http_ports: a direct GET, not
    # a guess. Among several ports confirmed as real HTTP (rare: a
    # device with two real web interfaces, e.g. a main app + an internal
    # console) the one with more content wins: a full frontend
    # is almost always more "substantial" than an internal service page -
    # verified on Home Assistant (frontend 8123: 8.9KB, Supervisor Observer
    # 4357: 1.1KB) and on a host with InfluxDB (8086: 19 bytes, the real app on
    # 3000: 63KB). It is not a guarantee, just a reasonable convention;
    # it can still be corrected by hand.
    confirmed = [p for p in stable_ports if p.get("has_http_title") or p.get("http_body_size")]
    if not confirmed:
        return None
    # If 80 or 443 are among the confirmed ports, they win anyway
    # before looking at the response size: they are such a widespread
    # convention that the user expects to find the main interface there,
    # even when a secondary service on the
    # same machine answers with a "heavier" page (verified:
    # a router with MiniDLNA on 8200 - larger response - was winning
    # over the real administration interface, which is on 80).
    for p in confirmed:
        if p["port"] in (80, 443):
            return p["port"]
    return max(confirmed, key=lambda p: float("inf") if p.get("has_http_title") else p["http_body_size"])["port"]


def _named_web_port(stable_ports: list[dict]) -> int | None:
    """The first port whose service nmap recognised as web."""
    return next((p["port"] for p in stable_ports if p["service"] in WEB_SERVICE_NAMES), None)


def _guess_port(ports: list[dict]) -> int:
    """Picks the most likely port for the device's web interface.

    Not all services run on 80 (e.g. Home Assistant on 8123): the choice
    is based on evidence, in order: a port that really answered over
    HTTP, one whose service is recognized as web, 80 if open; without
    evidence it stays 80. The user can still correct it in the confirmation pop-up.

    Ephemeral ports (>= 49152, IANA dynamic range) are excluded a priori: they
    are never a stable service, just a port open by chance at the instant
    of the scan (typical of phones). Using them as the "reference port" gave a
    link that stops working on the next round - verified on an iPhone
    that was assigned 49152 only because it was the only open port found.
    """
    stable_ports = [p for p in ports if p["port"] < EPHEMERAL_PORT_START]
    confirmed = _confirmed_web_port(stable_ports)
    if confirmed is not None:
        return confirmed
    named = _named_web_port(stable_ports)
    if named is not None:
        return named
    # 80 when it is open, and also when there is no proof that a port is web (neither an HTTP response nor a recognized
    # service): we do not invent one. A phone or a printer without a web
    # interface has no "right port": 80 stays by convention,
    # correctable by hand. Interfaces on non-standard ports are found with the
    # HTTP confirmation (_confirm_http_ports), not by guessing from the number.
    return 80


def web_identity(ports: list[dict]) -> dict:
    """Server and title read from the web port chosen as the default (if the confirmation
    GET found them): they are the best proof of what the device is."""
    chosen = _guess_port(ports)
    for p in ports:
        if p["port"] == chosen and p.get("http_body_size"):
            return {"http_server": p.get("http_server"), "http_title": p.get("http_page_title"),
                    "tls_subject": p.get("tls_subject")}
    return {}
