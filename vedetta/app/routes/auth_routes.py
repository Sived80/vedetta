# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The login pages of Docker mode (access.py lets them through without a session; under the Supervisor they answer 404).

GET/POST /login: the password, then a new session in a cookie (HttpOnly, SameSite=Lax; Secure with the __Host- name when the page is
HTTPS, also behind a trusted proxy). GET/POST /setup: only while no password exists, with the one-time code of the log. POST /logout:
the session ends on the server. Wrong attempts wait (auth/throttle.py); one scrypt at a time (it takes 128 MiB). Every refusal shows
the same words and status: nothing says whether the code, the password or the wait was wrong beyond what the person needs to retry.
The pages are plain HTML forms with no script (the page's CSP allows none here)."""
import asyncio
import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
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
throttle = Throttle()
setup_code = SetupCode()
_hashing = asyncio.Lock()
MAX_FORM_BYTES = 4096


def announce_setup() -> None:
    """At start in Docker with no password: the one-time code goes in the log, once (whoever reads the log controls the container)."""
    if runtime.is_docker() and not store.has_password():
        code = setup_code.make()
        logger.warning("Prima configurazione: apri la pagina di Vedetta e scegli la password. Codice monouso (valido 60 minuti): %s", code)


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
    body = await request.body()
    if len(body) > MAX_FORM_BYTES:
        raise HTTPException(413)
    return {k: v[0] for k, v in parse_qs(body.decode("utf-8", errors="replace"), max_num_fields=8).items()}


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
    form, client = await _form(request), _client(request)
    target = _next(form.get("next"))
    wait = throttle.wait(client)
    if wait > 0:
        return _page(request, "login.html", status=429, target=target, error="auth.wait", seconds=int(wait) + 1)
    stored = store.password_hash()
    async with _hashing:
        ok = bool(stored) and await asyncio.to_thread(passwords.verify, form.get("password", ""), stored)
    if not ok:
        throttle.failed(client)
        logger.info("Accesso rifiutato da %s", client)
        return _page(request, "login.html", status=401, target=target, error="auth.wrong")
    throttle.succeeded(client)
    if passwords.needs_rehash(stored):
        store.set_password_hash(await asyncio.to_thread(passwords.hash_password, form["password"]))
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
    form, client = await _form(request), _client(request)
    wait = throttle.wait(client)
    if wait > 0:
        return _page(request, "setup.html", status=429, error="auth.wait", seconds=int(wait) + 1, expired=False)
    if not setup_code.matches(form.get("code", "")):
        throttle.failed(client)
        logger.info("Codice di configurazione errato da %s", client)
        return _page(request, "setup.html", status=401, error="auth.code_wrong", expired=not setup_code.active())
    password = form.get("password", "")
    problem = passwords.problem(password) or (None if password == form.get("confirm") else "mismatch")
    if problem:
        return _page(request, "setup.html", status=400, error="auth." + problem, expired=False)
    async with _hashing:
        stored = await asyncio.to_thread(passwords.hash_password, password)
    if store.has_password():                       # two forms at once: the first one won
        raise HTTPException(404)
    store.set_password_hash(stored)
    setup_code.used()
    throttle.succeeded(client)
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
