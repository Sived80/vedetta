"""Registro degli eventi oltre a online/offline, per il Registro a livelli di /ha.

  min      cambi di stato dei dispositivi fissi (storico) + gli avvisi IMPORTANT
  normal   + cio' che conta per l'utente: avvisi (nuovo dispositivo, porte, IP
           cambiato o duplicato, piu' server DHCP), dispositivi aggiunti/eliminati,
           pausa e ripresa del controllo
  detail   + il lavoro del servizio: ricerche fatte, analisi dei dispositivi, ruoli di
           rete, offerta DHCP, uscita verso internet, ricerche annullate

Le voci tengono chiave e parametri, non il testo: la frase si traduce quando la si
legge, nella lingua di chi guarda. Ultime MAX_ENTRIES voci, salvate in un file JSON
Lines (sopravvivono al riavvio)."""
import itertools
import json
import threading
import time
from collections import deque

from .applog import logger
from .settings import CONFIG_DIR

MAX_ENTRIES = 400
PATH = CONFIG_DIR / "journal.jsonl"
LEVELS = ("min", "normal", "detail")
# Avvisi che compaiono anche nel livello minimo.
IMPORTANT = {"alert.new_device", "alert.ip_conflict", "alert.dhcp_multiple"}

_entries: deque = deque(maxlen=MAX_ENTRIES)
_lock = threading.Lock()
_seq = itertools.count(1)
_loaded = False


def _load() -> None:
    global _loaded, _seq
    if _loaded:
        return
    _loaded = True
    try:
        lines = PATH.read_text(encoding="utf-8").splitlines()[-MAX_ENTRIES:]
    except OSError:
        return
    last = 0
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict) and e.get("key"):
            _entries.append(e)
            last = max(last, int(e.get("id", 0)))
    _seq = itertools.count(last + 1)


def add(level: str, key: str, icon: str = "history", **params) -> None:
    """Nuova voce (level: normal | detail). Non solleva mai: il registro e' accessorio."""
    try:
        with _lock:
            _load()
            entry = {"id": next(_seq), "ts": time.time(), "level": level, "key": key, "icon": icon,
                     "params": {k: (v if isinstance(v, (int, float)) else str(v)) for k, v in params.items()}}
            _entries.append(entry)
            PATH.parent.mkdir(parents=True, exist_ok=True)
            # File ricompattato quando supera il doppio del massimo, altrimenti solo append.
            try:
                big = PATH.exists() and PATH.stat().st_size > 400 * MAX_ENTRIES
            except OSError:
                big = False
            if big:
                PATH.write_text("".join(json.dumps(e) + "\n" for e in _entries), encoding="utf-8")
            else:
                with PATH.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(entry) + "\n")
    except Exception:
        logger.exception("Registro eventi: voce non salvata")


def entries(level: str, limit: int) -> list[dict]:
    """Voci del livello richiesto (le piu' recenti per prime)."""
    if level not in ("normal", "detail"):
        return []
    allowed = {"normal"} if level == "normal" else {"normal", "detail"}
    with _lock:
        _load()
        items = [e for e in reversed(_entries) if e.get("level") in allowed]
    return items[:limit]
