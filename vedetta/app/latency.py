"""Device response time, measured in the same check cycle.

Measurement: ICMP echo through the `ping` command if present in the container (no
raw socket in Python); otherwise TCP connection time to the device's
port (even an RST "connection refused" is a valid response: the
time is still the round-trip one). Timeout ~1 s per device, all
in parallel with a cap on concurrent processes (1-CPU container).

The displayed value is a simple moving average, rounded to coarse steps:
a value that changes on every cycle would make the card be replaced (SSE event) on every
check. The calculation functions are pure and can be tested without network
(tests/check_interval_latency.py)."""
import asyncio
import re
import shutil
import time
from collections import deque

TIMEOUT = 1.0
MAX_CONCURRENT = 12   # concurrent ping processes / connections
WINDOW = 5            # moving average samples
MAX_SERIES_POINTS = 120

_TIME_RE = re.compile(r"time[=<]\s*([0-9.]+)\s*ms")


# ---- pure functions ----
def quantize(ms: float | None) -> int | None:
    """Rounds to steps: <10 ms step 1, <50 step 5, beyond step 25.
    Minimum 1 ms (below a millisecond is not a useful value)."""
    if ms is None or ms < 0:
        return None
    if ms < 10:
        return max(1, int(round(ms)))
    if ms < 50:
        return int(round(ms / 5.0) * 5)
    return int(round(ms / 25.0) * 25)


def color(ms: int | float | None) -> str | None:
    """Discrete quality (same names as the signal colours): green < 20 ms,
    yellow < 100 ms, red beyond."""
    if ms is None:
        return None
    if ms < 20:
        return "green"
    if ms < 100:
        return "yellow"
    return "red"


def quality(ms: int | float | None) -> str | None:
    return {"green": "good", "yellow": "fair", "red": "slow"}.get(color(ms) or "")


def reduce_series(points: list[tuple[float, float]], since: float, until: float,
                  max_points: int = MAX_SERIES_POINTS) -> dict:
    """Series [(ts, ms)] reduced to at most max_points points: the window is divided
    into equal buckets and the average of each bucket is kept. Also returns the overall average and
    maximum (None if there is no data)."""
    points = sorted(points)
    if not points:
        return {"from": int(since), "to": int(until), "points": [], "avg": None, "max": None}
    span = max(1.0, until - since)
    n = max(1, int(max_points))
    buckets: dict[int, list[float]] = {}
    for ts, ms in points:
        idx = min(n - 1, max(0, int((ts - since) / span * n)))
        buckets.setdefault(idx, []).append(ms)
    out = []
    for idx in sorted(buckets):
        vals = buckets[idx]
        mid = since + (idx + 0.5) * span / n
        out.append([int(mid), round(sum(vals) / len(vals), 1)])
    allv = [ms for _, ms in points]
    return {"from": int(since), "to": int(until), "points": out,
            "avg": round(sum(allv) / len(allv), 1), "max": round(max(allv), 1)}


class Tracker:
    """Per-device moving average and accumulation of the average per-minute sample."""

    def __init__(self, window: int = WINDOW) -> None:
        self._window = window
        self._win: dict[str, deque] = {}
        self._acc: dict[str, list[float]] = {}   # id -> [sum, n] of the current minute
        self._minute: int | None = None

    def add(self, device_id: str, ms: float | None) -> None:
        """New sample. ms None = no response: the window empties slowly
        (an old value does not stay forever)."""
        win = self._win.setdefault(device_id, deque(maxlen=self._window))
        if ms is None:
            if win:
                win.popleft()
            return
        win.append(ms)
        acc = self._acc.setdefault(device_id, [0.0, 0])
        acc[0] += ms
        acc[1] += 1

    def value(self, device_id: str) -> int | None:
        """Moving average rounded to steps (None if there are no samples)."""
        win = self._win.get(device_id)
        return quantize(sum(win) / len(win)) if win else None

    def reset(self, device_id: str) -> None:
        self._win.pop(device_id, None)
        self._acc.pop(device_id, None)

    def take_minute(self, now: float | None = None) -> list[tuple[str, float, float]]:
        """If the minute has changed returns [(device_id, ts, avg_ms)] of the minute
        just ended (a single sample per device) and starts again from zero;
        otherwise an empty list."""
        now = time.time() if now is None else now
        minute = int(now // 60)
        if self._minute is None:
            self._minute = minute
            return []
        if minute <= self._minute:
            return []
        ts = float(self._minute * 60)
        rows = [(i, ts, round(s / n, 1)) for i, (s, n) in self._acc.items() if n]
        self._acc = {}
        self._minute = minute
        return rows


tracker = Tracker()


# ---- measurement ----
_PING = shutil.which("ping")


async def _icmp_ms(ip: str, timeout: float) -> float | None:
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            _PING, "-c", "1", "-W", str(max(1, int(round(timeout)))), ip,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout + 0.5)
    except Exception:
        if proc is not None and proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        return None
    m = _TIME_RE.search(out.decode(errors="ignore"))
    return float(m.group(1)) if m else None


async def _tcp_ms(ip: str, port: int, timeout: float) -> float | None:
    start = time.perf_counter()
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=timeout)
    except ConnectionRefusedError:
        return (time.perf_counter() - start) * 1000.0  # RST: the host responded
    except Exception:
        return None
    ms = (time.perf_counter() - start) * 1000.0
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass
    return ms


async def measure(ip: str, port: int = 80, timeout: float = TIMEOUT) -> float | None:
    """Response time in ms (None if it does not respond): ICMP if `ping` exists,
    otherwise TCP. No second attempt: a powered-off host would cost 2 timeouts."""
    if _PING:
        return await _icmp_ms(ip, timeout)
    return await _tcp_ms(ip, port, timeout)


async def measure_many(targets: list[tuple[str, str, int]]) -> dict[str, float | None]:
    """targets: [(device_id, ip, port)] -> {device_id: ms | None}, in parallel."""
    sem = asyncio.Semaphore(MAX_CONCURRENT)

    async def one(ip: str, port: int) -> float | None:
        async with sem:
            return await measure(ip, port)

    results = await asyncio.gather(*(one(ip, port) for _, ip, port in targets), return_exceptions=True)
    return {t[0]: (r if isinstance(r, float) else None) for t, r in zip(targets, results)}
