import logging
from collections import deque
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from zoneinfo import ZoneInfo

from .paths import DATA_DIR as CONFIG_DIR
LOG_PATH = CONFIG_DIR / "dashboard.log"
_MAX_ENTRIES = 500
_SEP = "\t"

# Il container ha il fuso UTC: l'ora dei log va scritta esplicitamente in ora
# italiana, altrimenti risulta sfasata di 1-2 ore rispetto all'orologio reale.
TZ = ZoneInfo("Europe/Rome")


def _display_time(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, TZ).strftime("%Y-%m-%d %H:%M:%S")


def _parse_stored_time(text: str) -> str:
    """Le righe scritte prima di questa correzione sono senza fuso e in UTC (19
    caratteri); quelle nuove portano l'offset (es. +02:00)."""
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
    """Ricarica nel buffer le ultime righe del file: la pagina /log mostra
    anche gli eventi precedenti a un riavvio o a un deploy."""
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
        # Senza scrittura su disco il log resta solo in memoria: meglio
        # cosi' che impedire l'avvio del servizio.
        pass
    logger.propagate = True  # arriva comunque anche a systemd/journalctl


_setup()


def get_entries() -> list[dict]:
    """Piu' recente prima."""
    return list(reversed(_entries))
