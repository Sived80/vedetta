"""The one-time invitation to star the project on GitHub (config/star_hint.json).

It is shown once in the life of an installation, and the memory is on the server, not in the browser: another browser, another device
or an update never shows it again. An installation that already has history (an old one) is treated like a new one that has just
reached the age: it sees the invitation once, after the update. Nothing is sent anywhere; the invitation is only a link."""
from ..atomic import write_atomic
import json
import os
import time

from ..paths import DATA_DIR as CONFIG_DIR

STAR_PATH = CONFIG_DIR / "star_hint.json"
MIN_AGE_DAYS = 2        # how long the installation must have been watching before the invitation can come: a couple of days of use, never at once (VEDETTA_STAR_MIN_AGE_DAYS overrides it, for a test)

_done: bool | None = None


def done() -> bool:
    global _done
    if _done is None:
        try:
            _done = bool(json.loads(STAR_PATH.read_text(encoding="utf-8")).get("shown"))
        except (OSError, ValueError, AttributeError):
            _done = False
    return _done


def mark_done() -> None:
    """Remember for good that the invitation has been shown."""
    global _done
    _done = True
    write_atomic(STAR_PATH, lambda f: json.dump({"shown": time.time()}, f), ".star-", folder=CONFIG_DIR)


def should_show(first_ts: float | None, now: float | None = None) -> bool:
    """True when the invitation may appear: never shown, and the installation has history at least MIN_AGE_DAYS old."""
    if done():
        return False
    try:
        days = float(os.environ.get("VEDETTA_STAR_MIN_AGE_DAYS", MIN_AGE_DAYS))
    except ValueError:
        days = MIN_AGE_DAYS
    if days <= 0:
        return True             # the debug copy: no history needed
    return bool(first_ts) and (now if now is not None else time.time()) - first_ts >= days * 86400
