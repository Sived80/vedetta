"""The service's own log: a rotating file in the data folder (dashboard.log) and a short in-memory list of the latest entries, which the log page and the export read.
The time zone is given by Home Assistant through set_zone_provider: this module sits at the bottom of the layers and imports nothing from the app except paths."""
import logging
import os
from collections import deque
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from zoneinfo import ZoneInfo

from .paths import DATA_DIR as CONFIG_DIR
LOG_PATH = CONFIG_DIR / "dashboard.log"
_MAX_ENTRIES = 500
_SEP = "\t"

# The container has the UTC time zone: the log time must be written explicitly in the user's time zone
# (the one of Home Assistant, see ha_tz), otherwise it is hours off from the real clock.
_zone_provider = {"fn": None}   # ha_tz registers its zone() here when it is imported: the log stays at the bottom and imports nothing from `ha`


def set_zone_provider(provider) -> None:
    _zone_provider["fn"] = provider


def _tz():
    try:
        return _zone_provider["fn"]()
    except Exception:   # no provider yet, or it failed: the zone the log was first written for
        return ZoneInfo("Europe/Rome")


def _display_time(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, _tz()).strftime("%Y-%m-%d %H:%M:%S")


_entries: deque[dict] = deque(maxlen=_MAX_ENTRIES)

_LEVELS = {"debug": logging.DEBUG, "info": logging.INFO, "warning": logging.WARNING, "error": logging.ERROR}


def level_from(text) -> int:
    """The level named by the add-on option `log_level`; anything else (missing, unknown) is INFO."""
    return _LEVELS.get(str(text or "").strip().lower(), logging.INFO)


logger = logging.getLogger("dashboard")


def apply_level() -> None:
    logger.setLevel(level_from(os.environ.get("VEDETTA_LOG_LEVEL")))


apply_level()


class _BufferHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        _entries.append({
            "time": _display_time(record.created),
            "level": record.levelname,
            "message": record.getMessage(),
            "ts": record.created,
        })


class _FileFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        when = datetime.fromtimestamp(record.created, _tz()).isoformat(timespec="seconds")
        message = record.getMessage().replace("\n", " ").replace(_SEP, " ")
        return f"{when}{_SEP}{record.levelname}{_SEP}{message}"


def _setup() -> None:
    _load_previous()
    logger.addHandler(_BufferHandler())
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(_FileFormatter())
        logger.addHandler(handler)
    except OSError:
        # Without writing to disk the log stays in memory only: better
        # that than preventing the service from starting.
        pass
    logger.propagate = True  # it still reaches systemd/journalctl too


def _load_previous() -> None:
    """Reloads the last lines of the file into the buffer: the /log page also shows
    events from before a restart or a deploy."""
    try:
        lines = LOG_PATH.read_text(encoding="utf-8").splitlines()[-_MAX_ENTRIES:]
    except OSError:
        return
    for line in lines:
        parts = line.split(_SEP, 2)
        if len(parts) == 3:
            try:
                ts = datetime.fromisoformat(parts[0]).timestamp()
            except ValueError:
                ts = None
            _entries.append({"time": _parse_stored_time(parts[0]), "level": parts[1], "message": parts[2], "ts": ts})


def _parse_stored_time(text: str) -> str:
    """Lines written before this fix have no time zone and are in UTC (19
    characters); the new ones carry the offset (e.g. +02:00)."""
    try:
        if len(text) == 19:
            moment = datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        else:
            moment = datetime.fromisoformat(text)
        return moment.astimezone(_tz()).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return text


_setup()


def get_entries() -> list[dict]:
    """Most recent first."""
    return list(reversed(_entries))
