# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""Home Assistant ingress support (add-on).

Ingress serves the app under a prefix (/api/hassio_ingress/<token>) but
strips it before forwarding: the routes stay /, /ha, /api/...; only the GENERATED
URLs must be prefixed. The prefix arrives in X-Ingress-Path (or in
VEDETTA_BASE_PATH); absent = empty string and nothing changes compared to the LXC.

VEDETTA_INGRESS_ONLY=1 (off by default): 403 for anyone not coming from the Supervisor
(172.30.32.2). Not even localhost: with host_network another app on the host would reach the API. Only /healthz is answered
on localhost too (the watch loop of run.sh).

Every answer carries the security headers (SECURITY_HEADERS); the page gets a Content-Security-Policy with a new nonce at each
request, so only its own three inline scripts run (template_context gives the nonce to the template)."""
import os
import secrets
from urllib.parse import urlsplit

from . import runtime
from .paths import env_base_path, normalize_base

SUPERVISOR_IP = "172.30.32.2"
_ALLOWED_PEERS = {SUPERVISOR_IP}
_HEALTH_PEERS = {SUPERVISOR_IP, "127.0.0.1", "::1"}     # /healthz: also the watch loop of run.sh, which asks it from localhost
SECURITY_HEADERS = [(b"x-content-type-options", b"nosniff"), (b"x-frame-options", b"SAMEORIGIN"), (b"referrer-policy", b"same-origin")]


# Docker mode only: no access to the devices of the browser, no window of another site keeps a handle on this one.
DOCKER_HEADERS = [(b"permissions-policy", b"camera=(), microphone=(), geolocation=(), usb=(), serial=(), bluetooth=(), payment=()"),
                  (b"cross-origin-opener-policy", b"same-origin")]


def csp(nonce: str, ancestors: str = "") -> str:
    """Scripts only from the app or with the nonce of this page; inline style attributes stay (the page sets widths and colours).
    ancestors: other origins that may show the page in a frame (Docker: the dashboard "Webpage" of Home Assistant)."""
    return ("default-src 'self'; script-src 'self' 'nonce-%s'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
            "connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'self'%s; form-action 'self'" % (nonce, ancestors and " " + ancestors))


def frame_ancestors() -> str:
    """VEDETTA_FRAME_ANCESTORS in Docker: the origins (http(s)://host[:port], separated by spaces or commas) allowed to frame the page,
    e.g. the address of Home Assistant. Anything else in the list is dropped: a wildcard or a path would open the page to any site."""
    if not runtime.is_docker():
        return ""
    found = []
    for item in os.environ.get("VEDETTA_FRAME_ANCESTORS", "").replace(",", " ").split():
        try:
            parts = urlsplit(item)
            port = parts.port
        except ValueError:
            continue
        if parts.scheme in ("http", "https") and parts.hostname and "*" not in item and not (parts.path.strip("/") or parts.query or parts.username):
            found.append("%s://%s%s" % (parts.scheme, parts.hostname if ":" not in parts.hostname else "[%s]" % parts.hostname, ":%d" % port if port else ""))
    return " ".join(dict.fromkeys(found))


def ingress_only() -> bool:
    return os.environ.get("VEDETTA_INGRESS_ONLY", "").strip().lower() in ("1", "true", "yes", "on")


def base_from_headers(headers: dict[bytes, bytes]) -> str:
    raw = headers.get(b"x-ingress-path")
    return normalize_base(raw.decode("latin-1")) if raw else env_base_path()


class IngressMiddleware:
    """Pure ASGI (no BaseHTTPMiddleware: it does not buffer the SSE stream).
    Puts the prefix in request.state.base."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        # /healthz stays reachable by the watch loop of run.sh (from localhost), not by the rest of the network.
        if ingress_only():
            client = (scope.get("client") or ("",))[0]
            if client not in (_HEALTH_PEERS if scope.get("path") == "/healthz" else _ALLOWED_PEERS):
                if scope["type"] == "http":
                    body = b"Forbidden"
                    await send({"type": "http.response.start", "status": 403, "headers": [
                        (b"content-type", b"text/plain; charset=utf-8"), (b"content-length", str(len(body)).encode())]})
                    await send({"type": "http.response.body", "body": body})
                else:
                    await send({"type": "websocket.close", "code": 1008})
                return
        headers = dict(scope.get("headers", []))
        nonce = secrets.token_urlsafe(16)
        scope.setdefault("state", {}).update(base=base_from_headers(headers), nonce=nonce)
        await self.app(scope, receive, _with_security_headers(send, nonce, scope.get("path", "")) if scope["type"] == "http" else send)


def _with_security_headers(send, nonce: str, path: str = ""):
    """The security headers on every answer. In Docker also DOCKER_HEADERS and no cache for the API; with other frame ancestors there is
    no X-Frame-Options (CSP3: frame-ancestors wins, and an old browser reading SAMEORIGIN would refuse the frame of Home Assistant)."""
    ancestors = frame_ancestors()
    extra = [(b"content-security-policy", csp(nonce, ancestors).encode())]
    base = [h for h in SECURITY_HEADERS if not (ancestors and h[0] == b"x-frame-options")]
    if runtime.is_docker():
        extra += DOCKER_HEADERS + ([(b"cache-control", b"no-store")] if path.startswith("/api/") else [])

    async def wrapped(message) -> None:
        if message["type"] == "http.response.start":
            headers = list(message.get("headers", []))
            if extra and any(h[0] == b"cache-control" for h in extra):
                headers = [h for h in headers if h[0].lower() != b"cache-control"]
            message = {**message, "headers": headers + base + extra}
        await send(message)
    return wrapped


def template_context(request) -> dict:
    """Jinja2Templates context processor: `base` in every template."""
    return {"base": getattr(request.state, "base", ""), "nonce": getattr(request.state, "nonce", "")}
