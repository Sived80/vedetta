"""Pause of the periodic check: when it ends, how long it was, and its survival to a service restart (pause.json).

Pure state and persistence: telling the browsers and waking the cycle stays with DeviceState."""
import json
import time

from .applog import logger
from .storage import settings

FOREVER = float("inf")


def _file():
    return settings.CONFIG_DIR / "pause.json"


def _read(key: str):
    try:
        return json.loads(_file().read_text(encoding="utf-8")).get(key)
    except (OSError, ValueError, AttributeError):
        return None


class Pause:
    def __init__(self) -> None:
        self.until: float | None = self._load_until()     # epoch; inf = until resumed; None = active
        # Length of the timed pause in seconds (None = stopped until resumed or not paused): the page needs it to draw how far it has gone.
        self.total: float | None = self._load_total() if self.until not in (None, FOREVER) else None

    @staticmethod
    def _load_until() -> float | None:
        """The pause survives a service restart (like all settings)."""
        raw = _read("until")
        if raw == "forever":
            return FOREVER
        if isinstance(raw, (int, float)) and raw > time.time():
            return float(raw)
        return None

    @staticmethod
    def _load_total() -> float | None:
        raw = _read("total")
        return float(raw) if isinstance(raw, (int, float)) and raw > 0 else None

    def save(self) -> None:
        try:
            path = _file()
            if self.until is None:
                path.unlink(missing_ok=True)
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            until = "forever" if self.until == FOREVER else self.until
            path.write_text(json.dumps({"until": until, "total": self.total}), encoding="utf-8")
        except OSError:
            logger.exception("Pausa non salvata su disco")

    def remaining(self) -> float | None:
        """Seconds until the pause ends (inf = no expiry); None if not paused."""
        if self.until is None:
            return None
        left = self.until - time.time()
        if left <= 0:
            self.until = None
            self.total = None
            return None
        return left

    def start(self, minutes: int = 0) -> None:
        """minutes = 0 means until resumed."""
        self.until = time.time() + minutes * 60 if minutes else FOREVER
        self.total = minutes * 60.0 if minutes else None
        self.save()

    def stop(self) -> None:
        self.until = None
        self.total = None
        self.save()
