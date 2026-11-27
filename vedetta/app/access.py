# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""Who may use the app when it runs as a container of its own (Docker). Under the Supervisor this middleware does nothing: Home Assistant
logs the person in and ingress.py answers only the Supervisor.

In Docker the page is on a port of the network, so every request needs the session of the owner (auth/), except:
- /login and /setup (the forms to get one; /setup only before a password exists);
- /healthz, and only from the container itself (the healthcheck of Compose): from the network it is 404, it says nothing.

The Host of the request must be an address (IPv4, IPv6), localhost, a local name (.local, .lan, .home.arpa, .internal) or one of
VEDETTA_ALLOWED_HOSTS: a page of another site that points one of its own names to the LAN address of Vedetta (DNS rebinding) would
otherwise be "same origin" for the browser.

The headers only the Supervisor may send (X-Ingress-Path: the prefix of the URLs; X-Remote-User-ID: the person logged in Home Assistant)
are removed from every request: here anyone could write them.

Every request that changes something (POST, PUT, PATCH, DELETE) must come from the page itself (OWASP CSRF Prevention: fetch metadata,
then Origin or Referer): Sec-Fetch-Site same-origin, or an Origin equal to the address asked. The API calls also carry the header
X-Vedetta-Request, which a form of another site cannot send. A missing session gets 303 to the login for a page and 401 for the rest.
Pure ASGI, like ingress.py: it must not buffer the SSE stream."""
import ipaddress
import os
import secrets
from http.cookies import CookieError, SimpleCookie
from urllib.parse import quote, urlsplit

from . import runtime
from .auth import store
from .ingress import security_headers

SESSION_COOKIE = "vedetta_session"
SECURE_SESSION_COOKIE = "__Host-vedetta_session"      # a name the browser accepts only with Secure, Path=/ and no Domain (HTTPS)
PUBLIC = {"/login", "/setup"}
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
LOOPBACK = {"127.0.0.1", "::1"}
API_HEADER = b"x-vedetta-request"
_SUPERVISOR_ONLY = {b"x-ingress-path", b"x-remote-user-id"}
LOCAL_SUFFIXES = (".local", ".lan", ".home.arpa", ".internal")


def allowed_host(value: str) -> bool:
    """The Host header names this app: an address, localhost, a local name or a name of VEDETTA_ALLOWED_HOSTS (port ignored)."""
    value = (value or "").strip().lower()
    if not value or any(c in value for c in "/\\@ "):
        return False
    host = _host_part(value)
    return _is_address(host) or host == "localhost" or host.endswith(LOCAL_SUFFIXES) or host in _extra_hosts()


def _host_part(value: str) -> str:
    """The name or address of a Host header without the port ("[IPv6]:port", "name:port", a bare IPv6)."""
    if value.startswith("["):
        return value[1:value.find("]")] if "]" in value else ""
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def _is_address(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _extra_hosts() -> set[str]:
    return {h.strip().lower() for h in os.environ.get("VEDETTA_ALLOWED_HOSTS", "").replace(",", " ").split() if h.strip()}


def session_id(scope) -> str | None:
    """The session id from the cookie of the request (the secure name first)."""
    raw = b"; ".join(v for k, v in scope.get("headers", []) if k == b"cookie").decode("latin-1")
    if not raw:
        return None
    try:
        jar = SimpleCookie(raw)
    except CookieError:
        return None
    for name in (SECURE_SESSION_COOKIE, SESSION_COOKIE):
        if name in jar and jar[name].value:
            return jar[name].value
    return None


def _header(scope, name: bytes) -> str:
    for key, value in scope.get("headers", []):
        if key == name:
            return value.decode("latin-1")
    return ""


def same_origin(scope) -> bool:
    """The request was sent by a page of this app (see the module text)."""
    site = _header(scope, b"sec-fetch-site")
    if site:
        return site == "same-origin"
    host = _header(scope, b"host")
    origin = _header(scope, b"origin") or _origin_of(_header(scope, b"referer"))
    return bool(host) and bool(origin) and origin == "%s://%s" % (scope.get("scheme", "http"), host)


def _origin_of(url: str) -> str:
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    return "%s://%s" % (parts.scheme, parts.netloc) if parts.scheme and parts.netloc else ""


def _wants_page(scope) -> bool:
    return scope.get("method") in ("GET", "HEAD") and not scope.get("path", "").startswith(("/api/", "/static/"))


# The answers of the check: _APP lets the request through to the app, the others answer instead of it.
_APP = ("app",)
_HOST_REFUSED = ("plain", 400, b"Host not allowed: add it to VEDETTA_ALLOWED_HOSTS (see DOCKER.md)", b"text/plain; charset=utf-8")
_NOT_FOUND = ("plain", 404, b"Not Found", b"text/plain; charset=utf-8")
_FORBIDDEN = ("plain", 403, b"Forbidden", b"text/plain; charset=utf-8")
_LOGIN_REQUIRED = ("plain", 401, b'{"detail":"login required"}', b"application/json")
_CLOSE = ("close",)                                       # the app has no websocket of its own: nothing to open from the network


def decision(scope) -> tuple:
    """What the check answers to a request in Docker (see the module text): first what does not need a session, then the session."""
    return _without_session(scope) or _with_session(scope)


def _without_session(scope) -> tuple | None:
    """The Host, the healthcheck, the websockets, the origin of a change and the public forms, in this order; None = ask the session."""
    path = scope.get("path", "")
    if scope["type"] == "http" and not allowed_host(_header(scope, b"host")):
        return _HOST_REFUSED
    if path == "/healthz":
        return _APP if (scope.get("client") or ("",))[0] in LOOPBACK else _NOT_FOUND
    if scope["type"] == "websocket":
        return _CLOSE
    if scope.get("method", "GET") in UNSAFE and not same_origin(scope):
        return _FORBIDDEN
    return _APP if path in PUBLIC else None


def _with_session(scope) -> tuple:
    if store.valid(session_id(scope)):
        return _FORBIDDEN if _api_write_without_header(scope) else _APP
    return _to_login(scope) if _wants_page(scope) else _LOGIN_REQUIRED


def _api_write_without_header(scope) -> bool:
    """A change to the API without X-Vedetta-Request: a form of another site (it cannot send the header)."""
    return scope.get("method") in UNSAFE and scope.get("path", "").startswith("/api/") and _header(scope, API_HEADER) != "1"


def _to_login(scope) -> tuple:
    """A page without a session: to the setup while there is no password, else to the login (back to the page afterwards)."""
    if not store.has_password():
        return ("redirect", "/setup")
    path = scope.get("path", "")
    return ("redirect", "/login" if path in ("/", "/ha") else "/login?next=" + quote(path, safe="/"))


class AccessMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in ("http", "websocket") or not runtime.is_docker():
            await self.app(scope, receive, send)
            return
        scope["headers"] = [(k, v) for k, v in scope.get("headers", []) if k not in _SUPERVISOR_ONLY]
        answer = decision(scope)
        if answer is _APP:
            await self.app(scope, receive, send)
        elif answer[0] == "close":
            await send({"type": "websocket.close", "code": 1008})
        elif answer[0] == "redirect":
            await _redirect(send, answer[1], scope.get("path", ""))
        else:
            await _plain(send, answer[1], answer[2], answer[3], scope.get("path", ""))


def _headers(path: str) -> list:
    """The security headers of the app (ingress.py), on the answers of this check too."""
    return [h for h in security_headers(secrets.token_urlsafe(16), path) if h[0] != b"cache-control"] + [(b"cache-control", b"no-store")]


async def _plain(send, status: int, body: bytes, kind: bytes = b"text/plain; charset=utf-8", path: str = "") -> None:
    await send({"type": "http.response.start", "status": status, "headers": [
        (b"content-type", kind), (b"content-length", str(len(body)).encode())] + _headers(path)})
    await send({"type": "http.response.body", "body": body})


async def _redirect(send, location: str, path: str = "") -> None:
    await send({"type": "http.response.start", "status": 303, "headers": [
        (b"location", location.encode("latin-1")), (b"content-length", b"0")] + _headers(path)})
    await send({"type": "http.response.body", "body": b""})
