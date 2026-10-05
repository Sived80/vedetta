"""Home Assistant ingress support (add-on).

Ingress serves the app under a prefix (/api/hassio_ingress/<token>) but
strips it before forwarding: the routes stay /, /ha, /api/...; only the GENERATED
URLs must be prefixed. The prefix arrives in X-Ingress-Path (or in
VEDETTA_BASE_PATH); absent = empty string and nothing changes compared to the LXC.

VEDETTA_INGRESS_ONLY=1 (off by default): 403 for anyone not coming from the Supervisor
(172.30.32.2) or from localhost."""
import os

from .paths import env_base_path, normalize_base

SUPERVISOR_IP = "172.30.32.2"
_ALLOWED_PEERS = {SUPERVISOR_IP, "127.0.0.1", "::1"}


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
        # /healthz stays reachable by the Supervisor (add-on watchdog): it reveals nothing.
        if ingress_only() and scope.get("path") != "/healthz":
            client = (scope.get("client") or ("",))[0]
            if client not in _ALLOWED_PEERS:
                if scope["type"] == "http":
                    body = b"Forbidden"
                    await send({"type": "http.response.start", "status": 403, "headers": [
                        (b"content-type", b"text/plain; charset=utf-8"), (b"content-length", str(len(body)).encode())]})
                    await send({"type": "http.response.body", "body": body})
                else:
                    await send({"type": "websocket.close", "code": 1008})
                return
        headers = {k: v for k, v in scope.get("headers", [])}
        scope.setdefault("state", {})["base"] = base_from_headers(headers)
        await self.app(scope, receive, send)


def template_context(request) -> dict:
    """Jinja2Templates context processor: `base` in every template."""
    return {"base": getattr(request.state, "base", "")}
