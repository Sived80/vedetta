"""Internationalization: one folder per language in app/locales/<code>/ with
one or more flat JSON files key -> text (server.json for the templates and
Python, js.json for the browser). Adding a language = adding the folder
(with "lang.name" in server.json): nothing else to touch.

The language is a per-browser choice (cookie). It starts in English. The app
name ("Vedetta") is never translated."""
import contextvars
import json
import os
from pathlib import Path

LOCALES_DIR = Path(__file__).resolve().parent / "locales"
DEFAULT_LANG = "en"
COOKIE_NAME = "lang"
COOKIE_MAX_AGE = 60 * 60 * 24 * 365

_tables: dict[str, dict[str, str]] = {}
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


def use_request(request) -> str:
    """Language of the request: ?lang= in the address, then the X-Lang header, then
    the cookie (which the browser does not send back inside an iframe of another site)."""
    return use(request.query_params.get("lang") or request.headers.get("x-lang") or request.cookies.get(COOKIE_NAME)
               or os.environ.get("VEDETTA_LANGUAGE"))  # fallback: default language (HA add-on)


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
