"""Internationalization: one folder per language in app/locales/<code>/ with
one or more flat JSON files key -> text (server.json for the templates and
Python, js.json for the browser). Adding a language = adding the folder
(with "lang.name" in server.json): nothing else to touch.

Which language a request gets (resolve_request), the first that applies: the address (?lang=) or the X-Lang header; the choice the
logged-in Home Assistant user made (kept on the server, per user); the cookie of the browser; the app option `language` when it is
not `auto`; the language of Home Assistant; the browser's own (Accept-Language); English. The app name ("Vedetta") is never translated."""
import contextvars
import json
import os
from pathlib import Path

from .storage import userlang

LOCALES_DIR = Path(__file__).resolve().parent / "locales"
DEFAULT_LANG = "en"
COOKIE_NAME = "lang"
COOKIE_MAX_AGE = 60 * 60 * 24 * 365

_tables: dict[str, dict[str, str]] = {}
_system_lang: str | None = None     # the language of Home Assistant (read at start and every hour, see ha/ha_tz.py)
current_lang: contextvars.ContextVar[str] = contextvars.ContextVar("lang", default=DEFAULT_LANG)


def _load() -> None:
    for folder in sorted(LOCALES_DIR.iterdir()) if LOCALES_DIR.is_dir() else []:
        if not folder.is_dir():
            continue
        table: dict[str, str] = {}
        for file in sorted(folder.glob("*.json")):
            table.update(json.loads(file.read_text(encoding="utf-8")))
        _tables[folder.name] = table


_load()


def available() -> list[tuple[str, str]]:
    """[(code, name in its own language)], English first."""
    codes = sorted(_tables, key=lambda c: (c != DEFAULT_LANG, c))
    return [(c, _tables[c].get("lang.name", c)) for c in codes]


def normalize(code: str | None) -> str:
    return code if code in _tables else DEFAULT_LANG


def translate(lang: str, key: str, **params) -> str:
    table = _tables.get(lang, {})
    fallback = _tables.get(DEFAULT_LANG, {})
    n = params.get("n")
    text = None
    if n is not None:
        suffix = "_one" if n == 1 else "_other"
        text = table.get(key + suffix) or fallback.get(key + suffix)
    if text is None:
        text = table.get(key) or fallback.get(key) or key
    return text.format(**params) if params else text


def t(key: str, **params) -> str:
    """Text in the language of the current request/flow (also used
    by the Jinja templates as a global function)."""
    return translate(current_lang.get(), key, **params)


def use(lang: str | None) -> str:
    lang = normalize(lang)
    current_lang.set(lang)
    return lang


def match(code: str | None) -> str | None:
    """The language we have for a code such as "it", "it-IT" or "zh-Hans" (exact first, then the part before the dash), else None."""
    if not code:
        return None
    code = code.strip().replace("_", "-").lower()
    if code in _tables:
        return code
    base = code.split("-")[0]
    return base if base in _tables else None


def set_system_language(code: str | None) -> None:
    global _system_lang
    _system_lang = match(code)


def system_language() -> str | None:
    return _system_lang


def from_accept_language(header: str | None) -> str | None:
    """The first language we have in an Accept-Language header, best weight first ("it-IT,it;q=0.9,en;q=0.8")."""
    found = []
    for i, part in enumerate((header or "")[:300].split(",")):
        name, _, params = part.strip().partition(";")
        try:
            q = float(params.split("=")[1]) if "q=" in params else 1.0
        except (ValueError, IndexError):
            q = 0.0
        if name and name != "*" and q > 0:
            found.append((-q, i, name))
    for _, _, name in sorted(found):
        hit = match(name)
        if hit:
            return hit
    return None


def resolve_request(request) -> tuple[str, bool]:
    """(language, chosen): chosen is True when a person picked it (address, saved choice, cookie), False when it was worked out."""
    explicit = match(request.query_params.get("lang")) or match(request.headers.get("x-lang"))
    chosen = explicit or match(userlang.get(request.headers.get("x-remote-user-id"))) or match(request.cookies.get(COOKIE_NAME))
    if chosen:
        return use(chosen), True
    option = os.environ.get("VEDETTA_LANGUAGE", "").strip().lower()
    default = (match(option) if option != "auto" else None) or _system_lang or from_accept_language(request.headers.get("accept-language"))
    return use(default), False


def use_request(request) -> str:
    return resolve_request(request)[0]


def js_table(lang: str) -> dict[str, str]:
    """Only the keys for the browser, falling back to English."""
    merged = {k: v for k, v in _tables.get(DEFAULT_LANG, {}).items() if k.startswith("js.")}
    merged.update({k: v for k, v in _tables.get(lang, {}).items() if k.startswith("js.")})
    return merged


def t_or(key: str, default: str) -> str:
    """Like t(), but if the key does not exist in any language it returns the
    given value (labels coming from the devices, e.g. 'Model')."""
    if key in _tables.get(current_lang.get(), {}) or key in _tables.get(DEFAULT_LANG, {}):
        return t(key)
    return default
