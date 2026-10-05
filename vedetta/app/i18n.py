"""Internazionalizzazione: una cartella per lingua in app/locales/<codice>/ con
uno o piu' file JSON piatti chiave -> testo (server.json per i template e il
Python, js.json per il browser). Aggiungere una lingua = aggiungere la cartella
(con "lang.name" in server.json): nessun altro punto da toccare.

La lingua e' una scelta per browser (cookie). Parte in inglese. Il nome
dell'app ("Vedetta") non e' mai tradotto."""
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
    """[(codice, nome nella propria lingua)], l'inglese per primo."""
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
    """Testo nella lingua della richiesta/del flusso in corso (usata anche
    dai template Jinja come funzione globale)."""
    return translate(current_lang.get(), key, **params)


def use(lang: str | None) -> str:
    lang = normalize(lang)
    current_lang.set(lang)
    return lang


def use_request(request) -> str:
    """Lingua della richiesta: ?lang= nell'indirizzo, poi intestazione X-Lang, poi
    cookie (che dentro un iframe di un altro sito il browser non rimanda)."""
    return use(request.query_params.get("lang") or request.headers.get("x-lang") or request.cookies.get(COOKIE_NAME)
               or os.environ.get("VEDETTA_LANGUAGE"))  # ripiego: lingua predefinita (app di HA)


def js_table(lang: str) -> dict[str, str]:
    """Le sole chiavi per il browser, con ripiego sull'inglese."""
    merged = {k: v for k, v in _tables.get(DEFAULT_LANG, {}).items() if k.startswith("js.")}
    merged.update({k: v for k, v in _tables.get(lang, {}).items() if k.startswith("js.")})
    return merged


def t_or(key: str, default: str) -> str:
    """Come t(), ma se la chiave non esiste in nessuna lingua restituisce il
    valore dato (etichette che arrivano dai dispositivi, es. 'Model')."""
    if key in _tables.get(current_lang.get(), {}) or key in _tables.get(DEFAULT_LANG, {}):
        return t(key)
    return default
