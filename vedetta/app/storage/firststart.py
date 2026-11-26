"""When Vedetta first started on this installation (first_start.json), for the notice of the first hours on the page.

In the first hours the recognition is still gathering clues, and a brand or a type can change (a TV that speaks the protocol of another maker's
speakers looks like that maker until more clues come). The page says so for LEARNING_S after the first start. The date is written once and then only
read. An installation that already has history (an update from an older version) takes the date of its first event, so people who have used it
for weeks do not see the notice after an update. Nothing is sent anywhere."""
import json
import math
import time
from collections.abc import Callable

from ..atomic import write_atomic
from ..paths import DATA_DIR

PATH = DATA_DIR / "first_start.json"
LEARNING_S = 48 * 3600

_at: float | None = None


def _read() -> float | None:
    try:
        at = float(json.loads(PATH.read_text(encoding="utf-8"))["at"])
    except (OSError, ValueError, TypeError, KeyError):
        return None
    return at if math.isfinite(at) and at > 0 else None


def known() -> float | None:
    """The first start if already read in this run (no file, no history), else None."""
    return _at


def first_start(older: Callable[[], float | None], now: float | None = None) -> float:
    """The first start (seconds). Missing: the first event of the history (`older`, asked only then) or now, written for good."""
    global _at
    if _at is None:
        _at = _read()
    if _at is None:
        now = now if now is not None else time.time()
        first = older()
        _at = min(now, first) if first else now
        try:
            write_atomic(PATH, lambda f: json.dump({"at": _at}, f), ".first-", folder=DATA_DIR)
        except OSError:
            pass        # not written: the notice is only a help, it is tried again at the next start
    return _at


def learning_until(at: float, now: float | None = None) -> float | None:
    """Until when the notice of the first hours may appear, or None when that time is over."""
    until = at + LEARNING_S
    return until if (now if now is not None else time.time()) < until else None
