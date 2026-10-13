"""Why did the service restart? A small record of the run (tests/check_lifecycle.py): when it started, a heartbeat (time, memory, the longest delay of the event loop) and a mark when it stops cleanly.
At the next start the two runs are compared: a clean stop is a request from outside (Supervisor, update); a missing mark is a kill or a crash, and the last heartbeat says how long the process lived, how much
memory it held and whether the loop was blocked (the watchdog asks /healthz and gets no answer). Plain JSON, written without fsync: a beat a minute must not wear a memory card out."""
import asyncio
import json
import time
from pathlib import Path

from .atomic import write_atomic

BEAT_EVERY_S = 60
LOOP_BLOCKED_S = 10.0        # a delay of the loop longer than this is the first suspect of a restart by the watchdog (hypothesis to be confirmed by the next exports)
DEFAULT_MEMORY_LIMIT_MB = 700


def _write(path: Path, record: dict) -> None:
    try:
        write_atomic(path, lambda f: json.dump(record, f), ".run-", durable=False)
    except OSError:
        pass       # the record is a help for the diagnosis, never a reason to stop


def previous_run(path: Path) -> dict | None:
    """The record left by the previous run, None when there is none or it cannot be read."""
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) and isinstance(record.get("started"), (int, float)) else None


def begin(path: Path, now: float, rss_mb: int | None = None) -> None:
    _write(path, {"started": now, "beat": now, "rss_mb": rss_mb, "max_lag_s": 0.0, "clean": False})


def beat(path: Path, now: float, rss_mb: int | None = None, max_lag_s: float = 0.0) -> None:
    """A sign of life; the longest delay of the loop is kept for the whole run."""
    record = previous_run(path) or {"started": now}
    record.update(beat=now, rss_mb=rss_mb, max_lag_s=max(max_lag_s, record.get("max_lag_s") or 0.0), clean=False)
    _write(path, record)


def end(path: Path, now: float) -> None:
    record = previous_run(path) or {"started": now}
    record.update(beat=now, clean=True)
    _write(path, record)


def describe_previous(record: dict | None, now: float) -> tuple[str, dict]:
    """("first" | "clean" | "unclean", numbers) for the log and the export."""
    if record is None:
        return "first", {}
    ran = int(record["beat"] - record["started"])
    if record.get("clean"):
        return "clean", {"ran_s": ran, "down_s": int(now - record["beat"])}
    return "unclean", {"ran_s": ran, "silent_s": int(now - record["beat"]), "rss_mb": record.get("rss_mb"), "max_lag_s": record.get("max_lag_s") or 0.0}


def verdict(info: dict, memory_limit_mb: int = DEFAULT_MEMORY_LIMIT_MB) -> str:
    """The first suspect of an unclean end: "loop_blocked", "memory" or "unknown" (no more than a hypothesis: it says where to look)."""
    if (info.get("max_lag_s") or 0.0) >= LOOP_BLOCKED_S:
        return "loop_blocked"
    if (info.get("rss_mb") or 0) >= memory_limit_mb:
        return "memory"
    return "unknown"


previous: dict = {}      # how the previous run ended, for the export: {"kind": ..., "verdict": ..., numbers...}


def start(path: Path, rss_mb, log) -> "asyncio.Task":
    """At the start of the service: tells how the previous run ended (log and export), opens the record of this run and starts the heartbeat. Returns the task of the heartbeat (cancel it, then call stop)."""
    kind, info = describe_previous(previous_run(path), time.time())
    previous.clear()
    previous.update({"kind": kind, **info, **({"verdict": verdict(info)} if kind == "unclean" else {})})
    if kind == "unclean":
        log("Avvio precedente interrotto SENZA arresto pulito (visse %d s, ultimo segno di vita %d s prima, memoria %s MB, ritardo massimo del ciclo %.1f s): primo sospetto %s",
            info["ran_s"], info["silent_s"], info["rss_mb"], info["max_lag_s"], previous["verdict"])
    elif kind == "clean":
        log("Avvio precedente concluso con un arresto pulito (visse %d s, fermo da %d s)", info["ran_s"], info["down_s"])
    begin(path, time.time(), rss_mb())
    return asyncio.create_task(_heartbeat(path, rss_mb))


async def _heartbeat(path: Path, rss_mb) -> None:
    monitor = LoopLag()
    watcher = asyncio.create_task(monitor.run())
    try:
        while True:
            await asyncio.sleep(BEAT_EVERY_S)
            beat(path, time.time(), rss_mb(), monitor.take_max())
    finally:
        watcher.cancel()


async def stop(task: "asyncio.Task", path: Path) -> None:
    """At a clean stop: the heartbeat ends and the record says so."""
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    end(path, time.time())


class LoopLag:
    """The longest delay of the event loop since the last reading: a task that sleeps a short time and measures how late it wakes up."""

    def __init__(self, interval_s: float = 1.0) -> None:
        self.interval_s = interval_s
        self._max = 0.0

    async def run(self) -> None:
        while True:
            started = time.monotonic()
            await asyncio.sleep(self.interval_s)
            self._max = max(self._max, time.monotonic() - started - self.interval_s)

    def take_max(self) -> float:
        value, self._max = self._max, 0.0
        return round(value, 2)
