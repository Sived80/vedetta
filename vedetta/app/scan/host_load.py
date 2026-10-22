"""host_load: the load of the system under the app, from the pressure stall information of the kernel (/proc/pressure/{cpu,io,memory}: the "some" line, average of the last 60 seconds), which any process may read. It is a traffic
light for the heavy background work (busy: which resource is over its limit, or None) and a sampler that keeps the last samples and writes one line to the log each hour, so the limits can be tuned on real days.
Seen on the Proxmox history of 22 Oct: the disk of the host is saturated for about 22 minutes every three hours (backup), the CPU never; the limits below are hypotheses until a week of samples. Numbers only: no address, no name.
The kernel documentation names this use (pausing low priority batch jobs under pressure) and leaves the thresholds to the workload."""
import asyncio
import collections
import contextlib
import re
import time

from ..applog import logger

PRESSURE_DIR = "/proc/pressure"
RESOURCES = ("io", "cpu", "memory")
LIMITS = {"io": 15.0, "cpu": 25.0, "memory": 10.0}   # percent of the time with at least one task stalled, average of 60 s
SAMPLE_S = 60
KEEP_SAMPLES = 180                                     # three hours of samples
_SOME = re.compile(r"^some\s+avg10=[\d.]+\s+avg60=([\d.]+)\s", re.M)

_samples: collections.deque = collections.deque(maxlen=KEEP_SAMPLES)
_deferred: dict = {"count": 0, "last_reason": None, "last_at": None}
_hour: dict = {"max": {}, "deferred_at_start": 0, "started": None}
_task: asyncio.Task | None = None


def parse(text) -> float | None:
    """The average of the last 60 seconds of the line "some" of a pressure file; None if there is no such line."""
    match = _SOME.search(text or "") if isinstance(text, str) else None
    return float(match.group(1)) if match else None


def _read_file(path: str) -> float | None:
    try:
        with open(path, encoding="ascii") as f:
            return parse(f.read())
    except OSError:
        return None


def read(folder: str = PRESSURE_DIR) -> dict[str, float] | None:
    """One value per resource that can be read and understood; None when the kernel gives nothing at all."""
    values = {name: _read_file(f"{folder}/{name}") for name in RESOURCES}
    return {name: value for name, value in values.items() if value is not None} or None


def busy(reading: dict | None = None) -> str | None:
    """The resource that is over its limit (the first, in the order io, cpu, memory), or None: at the limit is still free, and without a reading nothing is blocked."""
    reading = read() if reading is None else reading
    return next((name for name in RESOURCES if (reading or {}).get(name, 0.0) > LIMITS[name]), None)


def note_deferred(reason: str, now: float | None = None) -> None:
    _deferred.update(count=_deferred["count"] + 1, last_reason=reason, last_at=time.time() if now is None else now)


def sample_once(now: float, reader=read) -> None:
    """One sample into the ring; the line of the log once an hour (the first sample only starts the clock)."""
    reading = reader()
    if not reading:
        _samples.append({"t": now})
        return
    _samples.append({"t": now, **reading})
    if _hour["started"] is None:
        _hour.update(started=now, deferred_at_start=_deferred["count"])
    for name, value in reading.items():
        _hour["max"][name] = max(value, _hour["max"].get(name, 0.0))
    if now - _hour["started"] >= 3600:
        peaks = ", ".join(f"{name} {_hour['max'][name]:.1f}%" for name in RESOURCES if name in _hour["max"])
        logger.info("Host load: in the last hour the highest pressure was %s; heavy scans put off: %d", peaks, _deferred["count"] - _hour["deferred_at_start"])
        _hour.update(max={}, started=now, deferred_at_start=_deferred["count"])


def manifest_part() -> dict:
    """What the export says: whether anything was readable, the limits, the last reading, the deferrals and the last samples (numbers only)."""
    values = [s for s in _samples if len(s) > 1]
    return {"available": bool(values), "limits": dict(LIMITS), "last": {k: v for k, v in (values[-1] if values else {}).items() if k != "t"},
            "deferred": dict(_deferred), "samples": [dict(s) for s in _samples]}


_reader = read


async def _loop() -> None:
    while True:
        sample_once(time.time(), reader=_reader)
        await asyncio.sleep(SAMPLE_S)


def start() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())


async def stop() -> None:
    global _task
    if _task:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _task
        _task = None
