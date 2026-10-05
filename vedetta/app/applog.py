import logging
from collections import deque
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from zoneinfo import ZoneInfo

from .paths import DATA_DIR as CONFIG_DIR
LOG_PATH = CONFIG_DIR / "dashboard.log"
_MAX_ENTRIES = 500
_SEP = "\t"

# The container has the UTC time zone: the log time must be written explicitly in
# Italian time, otherwise it is 1-2 hours off from the real clock.
TZ = ZoneInfo("Europe/Rome")


def _display_time(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, TZ).strftime("%Y-%m-%d %H:%M:%S")


def _parse_stored_time(text: str) -> str:
    """Lines written before this fix have no time zone and are in UTC (19
    characters); the new ones carry the offset (e.g. +02:00)."""
    try:
        if len(text) == 19:
            moment = datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        else:
            moment = datetime.fromisoformat(text)
        return moment.astimezone(TZ).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return text


_entries: deque[dict] = deque(maxlen=_MAX_ENTRIES)

logger = logging.getLogger("dashboard")
logger.setLevel(logging.INFO)


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
        when = datetime.fromtimestamp(record.created, TZ).isoformat(timespec="seconds")
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


_setup()


def get_entries() -> list[dict]:
    """Most recent first."""
    return list(reversed(_entries))
