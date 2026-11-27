# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The health findings a person chose to hide (config/health_hidden.json).

The choice is about the network, not about a screen: it lives on the server, so the phone and the computer show the same. Only
ids (rule and device key, never a name) are kept, at most MAX_HIDDEN of them (the oldest choice goes first)."""
from ..atomic import write_atomic
import json
import threading

from ..paths import DATA_DIR as CONFIG_DIR

PATH = CONFIG_DIR / "health_hidden.json"
MAX_HIDDEN = 500
MAX_ID_LEN = 200

_cache: list[str] | None = None
_lock = threading.Lock()          # apply reads, changes and writes in a worker thread: two choices made together must not lose one


def _valid(finding_id) -> bool:
    return isinstance(finding_id, str) and 0 < len(finding_id) <= MAX_ID_LEN


def load() -> list[str]:
    global _cache
    if _cache is None:
        try:
            raw = json.loads(PATH.read_text(encoding="utf-8")).get("hidden")
        except (OSError, ValueError, AttributeError):
            raw = None
        _cache = [x for x in raw if _valid(x)] if isinstance(raw, list) else []
    return list(_cache)


def apply(hide, show) -> list[str]:
    """Hides the ids in `hide`, shows again the ones in `show`; returns the list now kept. Anything that is not a short text is ignored."""
    with _lock:
        return _apply(hide, show)


def _apply(hide, show) -> list[str]:
    global _cache
    gone = {x for x in show if _valid(x)}
    current = [x for x in load() if x not in gone]
    seen = gone | set(current)                    # a set: the lookup stays quick on a long list
    for finding_id in hide:
        if _valid(finding_id) and finding_id not in seen:
            current.append(finding_id)
            seen.add(finding_id)
    current = current[-MAX_HIDDEN:]
    write_atomic(PATH, lambda f: json.dump({"hidden": current}, f, ensure_ascii=False), ".health-hidden-")
    _cache = current
    return list(current)
