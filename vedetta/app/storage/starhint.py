"""The one-time invitation to star the project on GitHub (config/star_hint.json).

It is shown once in the life of an installation, and the memory is on the server, not in the browser: another browser, another device
or an update never shows it again. An installation that already has history (an old one) is treated like a new one that has just
reached the age: it sees the invitation once, after the update. Nothing is sent anywhere; the invitation is only a link.
The app option `star_hint: false` (VEDETTA_STAR_HINT=false) switches it off for good."""
import json
import os
import tempfile
import time

from ..paths import DATA_DIR as CONFIG_DIR

STAR_PATH = CONFIG_DIR / "star_hint.json"
MIN_AGE_DAYS = 3        # how long the installation must have been watching before the invitation can come

_done: bool | None = None


def enabled() -> bool:
    return os.environ.get("VEDETTA_STAR_HINT", "true").strip().lower() not in ("false", "0", "no", "off")


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
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=CONFIG_DIR, prefix=".star-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"shown": time.time()}, f)
        os.replace(tmp, STAR_PATH)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def should_show(first_ts: float | None, now: float | None = None) -> bool:
    """True when the invitation may appear: on, never shown, and the installation has history at least MIN_AGE_DAYS old."""
    if not enabled() or done() or not first_ts:
        return False
    return (now if now is not None else time.time()) - first_ts >= MIN_AGE_DAYS * 86400
