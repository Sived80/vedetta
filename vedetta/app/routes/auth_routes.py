# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The login pages of Docker mode (access.py lets them through without a session; under the Supervisor they answer 404).

GET/POST /login: the password, then a new session in a cookie (HttpOnly, SameSite=Lax; Secure with the __Host- name when the page is
HTTPS, also behind a trusted proxy). GET/POST /setup: only while no password exists, with the one-time code of the log. POST /logout:
the session ends on the server. The pages are plain HTML forms with no script (the page's CSP allows none here).

Guessing (security review of 27/11): one check at a time (scrypt takes 128 MiB), and an attempt that arrives while another is being
checked is refused at once (429) instead of waiting in a queue; each attempt is counted as wrong BEFORE its check and cleared when it
was right, so attempts sent together cannot all pass the wait first (auth/throttle.py: the long wait per address, a short one for the
whole app). The body of a form is refused above MAX_FORM_BYTES by its Content-Length and read only up to that size."""
import asyncio
import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .. import i18n, runtime
from ..access import SECURE_SESSION_COOKIE, SESSION_COOKIE, session_id
from ..applog import logger
from ..auth import passwords, store
from ..auth.setup import SetupCode
from ..auth.throttle import Throttle
from ..ingress import template_context
from ..paths import env_base_path

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates", context_processors=[template_context])
throttle_login = Throttle()
throttle_setup = Throttle()            # counted apart: wrong logins never block the first setup, nor the other way round
setup_code = SetupCode()
_checking = asyncio.Lock()
MAX_FORM_BYTES = 4096
MAX_FIELDS = 8


class FormError(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(status)
        self.status = status


def announce_setup() -> None:
    """At start in Docker with no password: the one-time code goes in the log, once (whoever reads the log controls the container)."""
    if runtime.is_docker() and not store.has_password():
        code = setup_code.make()
        # In English (the rest of the log is Italian): this line is read by whoever installs the container, anywhere.
        logger.warning("FIRST SETUP: open the Vedetta page (port %d) and choose the password. One-time code, valid 60 minutes: %s",
                       runtime.port(), code)


def _secure(request: Request) -> bool:
    """Whether the cookie gets Secure: VEDETTA_COOKIE_SECURE=true/false, else auto (the page is HTTPS; behind a proxy uvicorn takes the
    scheme from X-Forwarded-Proto only for the addresses in --forwarded-allow-ips)."""
    chosen = os.environ.get("VEDETTA_COOKIE_SECURE", "auto").strip().lower()
    if chosen in ("1", "true", "yes", "on"):
        return True
    if chosen in ("0", "false", "no", "off"):
        return False
    return request.url.scheme == "https"


def _client(request: Request) -> str:
    return request.client.host if request.client else "?"


def _next(value: str | None) -> str:
    """Where to go after the login: only a path of this app ("/ha?x=1"), never another host ("//evil", "https://...")."""
    value = value or ""
    parts = urlsplit(value)
    if not value.startswith("/") or value.startswith("//") or "\\" in value or parts.scheme or parts.netloc:
        return "/ha"
    return value


def _page(request: Request, name: str, status: int = 200, **ctx) -> HTMLResponse:
    lang = i18n.use_request(request)
    tr = lambda key, **p: i18n.translate(lang, key, **p)   # noqa: E731
    response = templates.TemplateResponse(request, name, {"lang": lang, "tr": tr, "min_length": passwords.MIN_LENGTH, **ctx}, status_code=status)
    response.headers["Cache-Control"] = "no-store"
    return response


def _logged_in(request: Request, target: str) -> RedirectResponse:
    response = RedirectResponse(env_base_path() + target, status_code=303)
    secure = _secure(request)
    response.set_cookie(SECURE_SESSION_COOKIE if secure else SESSION_COOKIE, store.new_session(), max_age=store.ABSOLUTE_S,
                        httponly=True, samesite="lax", secure=secure, path="/")
    return response


async def _form(request: Request) -> dict:
    """The fields of a small form: 413 above MAX_FORM_BYTES (by Content-Length first, then while reading), 400 for a broken or crowded one."""
    try:
        declared = int(request.headers.get("content-length") or 0)
    except ValueError:
        raise FormError(400) from None
    if declared > MAX_FORM_BYTES:
        raise FormError(413)
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_FORM_BYTES:
            raise FormError(413)
    try:
        fields = parse_qs(body.decode("utf-8"), max_num_fields=MAX_FIELDS, strict_parsing=False)
    except (ValueError, UnicodeDecodeError):
        raise FormError(400) from None
    return {k: v[0] for k, v in fields.items()}


async def _checked(throttle: Throttle, client: str, check) -> bool | None:
    """Runs check() (a scrypt, in a thread) for one attempt: None when it must wait (the address or the app is waiting, or another
    attempt is being checked right now), else whether it was right. The attempt counts as wrong before the check."""
    if _checking.locked() or throttle.wait(client) > 0:
        return None
    async with _checking:
        if throttle.wait(client) > 0:
            return None
        throttle.failed(client)
        ok = await asyncio.to_thread(check)
    if ok:
        throttle.succeeded(client)
    return ok


def _wait_seconds(throttle: Throttle, client: str) -> int:
    return max(1, int(throttle.wait(client)) + 1)


def _docker_only() -> None:
    if not runtime.is_docker():
        raise HTTPException(404)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/ha"):      # noqa: A002  the name of the address parameter
    _docker_only()
    if not store.has_password():
        return RedirectResponse(env_base_path() + "/setup", status_code=303)
    return _page(request, "login.html", target=_next(next))


@router.post("/login")
async def login(request: Request):
    _docker_only()
    client = _client(request)
    try:
        form = await _form(request)
    except FormError as exc:
        return PlainTextResponse("Bad request", status_code=exc.status)
    target = _next(form.get("next"))
    stored = store.password_hash()
    password = form.get("password", "")
    ok = await _checked(throttle_login, client, lambda: bool(stored) and passwords.verify(password, stored))
    if ok is None:
        return _page(request, "login.html", status=429, target=target, error="auth.wait", seconds=_wait_seconds(throttle_login, client))
    if not ok:
        logger.info("Accesso rifiutato da %s", client)
        return _page(request, "login.html", status=401, target=target, error="auth.wrong")
    if passwords.needs_rehash(stored):
        store.set_password_hash(await asyncio.to_thread(passwords.hash_password, password))
    logger.info("Accesso da %s", client)
    return _logged_in(request, target)


@router.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    _docker_only()
    if store.has_password():
        raise HTTPException(404)
    return _page(request, "setup.html", expired=not setup_code.active())


@router.post("/setup")
async def setup(request: Request):
    _docker_only()
    if store.has_password():
        raise HTTPException(404)
    client = _client(request)
    try:
        form = await _form(request)
    except FormError as exc:
        return PlainTextResponse("Bad request", status_code=exc.status)
    ok = await _checked(throttle_setup, client, lambda: setup_code.matches(form.get("code", "")))
    if ok is None:
        return _page(request, "setup.html", status=429, error="auth.wait", seconds=_wait_seconds(throttle_setup, client), expired=False)
    if not ok:
        logger.info("Codice di configurazione errato da %s", client)
        return _page(request, "setup.html", status=401, error="auth.code_wrong", expired=not setup_code.active())
    password = form.get("password", "")
    problem = passwords.problem(password) or (None if password == form.get("confirm") else "mismatch")
    if problem:
        return _page(request, "setup.html", status=400, error="auth." + problem, expired=False)
    async with _checking:
        stored = await asyncio.to_thread(passwords.hash_password, password)
    if store.has_password() or not setup_code.active():       # two forms at once: the first one won
        raise HTTPException(404)
    store.set_password_hash(stored)
    setup_code.used()
    logger.warning("Password di Vedetta impostata dalla pagina (da %s)", client)
    return _logged_in(request, "/ha")


@router.post("/logout")
async def logout(request: Request):
    _docker_only()
    store.drop(session_id(request.scope))
    response = RedirectResponse(env_base_path() + "/login", status_code=303)
    for name in (SESSION_COOKIE, SECURE_SESSION_COOKIE):
        response.delete_cookie(name, path="/", secure=name == SECURE_SESSION_COOKIE, httponly=True, samesite="lax")
    return response
