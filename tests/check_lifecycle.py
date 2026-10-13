"""Why did the service restart? A real export (a user's, 288 starts in 5 days, about one every 19 minutes, no stop line before any of them) cannot say: the log is silent before each start, so the process
was ended from outside (a watchdog, a memory kill, the host) or it hung, and the log does not tell which. The service now keeps a small record of its run: when it started, a heartbeat (time, memory, the longest
delay of the event loop), and a mark when it stops cleanly. At the next start it compares: a clean stop is a request from outside (Supervisor, update), a missing mark is a kill or a crash, and the heartbeat says how
long the process lived after the last beat, how much memory it held and whether the loop was blocked. The record is plain JSON, written without fsync (a beat every minute must not wear a memory card out)."""
import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import lifecycle  # noqa: E402

path = Path(tempfile.mkdtemp()) / "run.json"
T0 = 1_800_000_000.0

# 1) the first start: nothing before it
assert lifecycle.previous_run(path) is None
assert lifecycle.describe_previous(None, T0) == ("first", {})

# 2) a clean stop is told as such
lifecycle.begin(path, T0, rss_mb=80)
lifecycle.beat(path, T0 + 60, rss_mb=82, max_lag_s=0.4)
lifecycle.end(path, T0 + 100)
kind, info = lifecycle.describe_previous(lifecycle.previous_run(path), T0 + 130)
assert kind == "clean" and info["ran_s"] == 100 and info["down_s"] == 30, (kind, info)

# 3) a start with no clean stop before it: killed or crashed; it says when the last sign of life was, the memory, the longest delay of the loop
lifecycle.begin(path, T0 + 200, rss_mb=80)
lifecycle.beat(path, T0 + 260, rss_mb=95, max_lag_s=48.0)
lifecycle.beat(path, T0 + 320, rss_mb=140, max_lag_s=48.0)
kind, info = lifecycle.describe_previous(lifecycle.previous_run(path), T0 + 540)
assert kind == "unclean", kind
assert info == {"ran_s": 120, "silent_s": 220, "rss_mb": 140, "max_lag_s": 48.0}, info
assert lifecycle.verdict(info) == "loop_blocked", "a long delay of the loop is the first suspect (the watchdog asks the service and gets no answer)"
assert lifecycle.verdict({"ran_s": 120, "silent_s": 10, "rss_mb": 900, "max_lag_s": 0.2}, memory_limit_mb=800) == "memory"
assert lifecycle.verdict({"ran_s": 120, "silent_s": 10, "rss_mb": 90, "max_lag_s": 0.2}) == "unknown"

# 4) a record that is damaged or from another version never stops the start
path.write_text("{not json", encoding="utf-8")
assert lifecycle.previous_run(path) is None
path.write_text(json.dumps({"started": "x"}), encoding="utf-8")
assert lifecycle.describe_previous(lifecycle.previous_run(path), T0)[0] == "first"

# 5) no temporary file is left behind, and the beat does not use fsync (a beat a minute on a memory card)
calls: list = []
real = os.fsync
os.fsync = lambda fd: (calls.append(1), real(fd))[1]
try:
    lifecycle.begin(path, T0, rss_mb=1)
    lifecycle.beat(path, T0 + 1, rss_mb=1, max_lag_s=0.0)
finally:
    os.fsync = real
assert not calls, "the beat must not force the disk"
assert not list(path.parent.glob("*.tmp"))

# 7) at the start of the service: the previous run is told in the log and kept for the export; the heartbeat starts and a clean stop is marked
logged: list = []


async def whole_run(previous_never_stopped=True):
    if previous_never_stopped:
        lifecycle.begin(path, time.time() - 50, rss_mb=70)         # a run that never stopped cleanly, 50 s ago
    task = lifecycle.start(path, lambda: 77, lambda msg, *a: logged.append(msg % a))
    assert not task.done()
    await lifecycle.stop(task, path)


asyncio.new_event_loop().run_until_complete(whole_run())
assert logged and "SENZA arresto pulito" in logged[0], logged
assert lifecycle.previous["kind"] == "unclean" and lifecycle.previous["verdict"] in ("loop_blocked", "memory", "unknown"), lifecycle.previous
kind, _ = lifecycle.describe_previous(lifecycle.previous_run(path), T0 + 99999999)
assert kind == "clean", "the stop was marked"
logged.clear()
asyncio.new_event_loop().run_until_complete(whole_run(previous_never_stopped=False))      # the run before stopped cleanly
assert "arresto pulito" in logged[0] and lifecycle.previous["kind"] == "clean", logged

# 6) the loop monitor: a blocked loop is seen as a long delay
async def blocked():
    monitor = lifecycle.LoopLag(interval_s=0.05)
    task = asyncio.create_task(monitor.run())
    await asyncio.sleep(0.12)
    time.sleep(0.4)            # the loop is blocked for 0.4 s
    await asyncio.sleep(0.12)
    task.cancel()
    return monitor.take_max()


lag = asyncio.new_event_loop().run_until_complete(blocked())
assert 0.3 <= lag < 1.5, lag
print("TUTTO OK")
