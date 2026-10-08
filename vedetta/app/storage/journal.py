"""Event log beyond online/offline, for the level-based Log of /ha.

  min      state changes of fixed devices (history) + IMPORTANT alerts
  normal   + what matters to the user: alerts (new device, ports, IP
           changed or duplicated, multiple DHCP servers), devices added/deleted,
           pause and resume of the checks
  detail   + the service's work: searches done, device analyses, network
           roles, DHCP offer, exit towards the internet, cancelled searches

The entries keep a key and parameters, not the text: the sentence is translated when
it is read, in the language of the viewer. Last MAX_ENTRIES entries, saved in a JSON
Lines file (they survive a restart)."""
import itertools
import json
import threading
import time
from collections import deque

from ..applog import logger
from .settings import CONFIG_DIR

MAX_ENTRIES = 400
PATH = CONFIG_DIR / "journal.jsonl"
LEVELS = ("min", "normal", "detail")
# Alerts that also appear at the minimum level.
IMPORTANT = {"alert.new_device", "alert.ip_conflict", "alert.dhcp_multiple", "alert.other_device"}

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
    """New entry (level: normal | detail). Never raises: the log is auxiliary."""
    try:
        with _lock:
            _load()
            entry = {"id": next(_seq), "ts": time.time(), "level": level, "key": key, "icon": icon,
                     "params": {k: (v if isinstance(v, (int, float)) else str(v)) for k, v in params.items()}}
            _entries.append(entry)
            PATH.parent.mkdir(parents=True, exist_ok=True)
            # File compacted when it exceeds twice the maximum, otherwise append only.
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
    """Entries of the requested level (most recent first)."""
    if level not in ("normal", "detail"):
        return []
    allowed = {"normal"} if level == "normal" else {"normal", "detail"}
    with _lock:
        _load()
        items = [e for e in reversed(_entries) if e.get("level") in allowed]
    return items[:limit]
