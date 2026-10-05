"""Supporto all'ingress di Home Assistant (add-on).

L'ingress serve l'app sotto un prefisso (/api/hassio_ingress/<token>) ma lo
toglie prima di inoltrare: le route restano /, /ha, /api/...; vanno prefissati
solo gli URL GENERATI. Il prefisso arriva in X-Ingress-Path (o in
VEDETTA_BASE_PATH); assente = stringa vuota e nulla cambia rispetto all'LXC.

VEDETTA_INGRESS_ONLY=1 (spento di default): 403 a chi non arriva dal Supervisor
(172.30.32.2) o da localhost."""
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
    """ASGI puro (niente BaseHTTPMiddleware: non bufferizza il flusso SSE).
    Mette il prefisso in request.state.base."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        # /healthz resta raggiungibile dal Supervisor (watchdog dell'add-on): non rivela nulla.
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
    """Context processor di Jinja2Templates: `base` in ogni template."""
    return {"base": getattr(request.state, "base", "")}
