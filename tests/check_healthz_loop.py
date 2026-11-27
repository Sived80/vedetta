# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""/healthz says whether the service does its work, not only whether the web server answers: a probe that never ends used to stop
every check while /healthz kept answering ok, so the watch loop of run.sh never restarted the service. Now /healthz is 503 when
the loop of the checks has not turned for max(5 minutes, 5 intervals); a pause keeps the loop turning (it waits at most one interval);
before the first turn nothing is judged.
    python tests/check_healthz_loop.py"""
import asyncio
import os
import sys
import tempfile

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from fastapi.testclient import TestClient  # noqa: E402
from app import main, state_cycle  # noqa: E402
from app.state import state  # noqa: E402

stalled = state_cycle.stalled

# 1) the pure rule
assert stalled(None, 1000.0, 30) == (False, None)                       # before the first turn: not judged
assert stalled(1000.0, 1000.0 + 299, 30)[0] is False                    # the floor: 5 minutes
assert stalled(1000.0, 1000.0 + 301, 30) == (True, 301)
assert stalled(1000.0, 1000.0 + 1400, 300)[0] is False                  # long interval: 5 intervals
assert stalled(1000.0, 1000.0 + 1501, 300)[0] is True

# 2) the route: 200 while the loop turns, 503 when it is stuck
client = TestClient(main.app)
state._alive_at = None
r = client.get("/healthz")
assert r.status_code == 200 and r.json()["ok"] is True, r.text
import time  # noqa: E402
state._alive_at = time.monotonic() - 10
assert client.get("/healthz").status_code == 200
state._alive_at = time.monotonic() - 3600
r = client.get("/healthz")
assert r.status_code == 503 and r.json()["ok"] is False and r.json()["loop_age_s"] >= 3600, r.text


# 3) the loop marks a turn even while paused, and a cycle that hangs stops the turns
class Fake:
    def __init__(self, paused):
        self._wake = asyncio.Event()
        self._force = False
        self._alive_at = None
        self.paused = paused
        self.ready = asyncio.Event()

    def paused_remaining(self):
        return 60.0 if self.paused else None


async def turns(paused):
    fake = Fake(paused)
    hung = asyncio.Event()

    async def run_cycle(st, gap):
        hung.set()
        await asyncio.Event().wait()            # a probe that never ends

    async def sleep_until_wake(st):
        await asyncio.sleep(0)

    real_run, real_sleep = state_cycle._run_cycle, state_cycle._sleep_until_wake
    state_cycle._run_cycle, state_cycle._sleep_until_wake = run_cycle, sleep_until_wake
    try:
        task = asyncio.create_task(state_cycle.loop(fake, 0))
        for _ in range(20):
            await asyncio.sleep(0)
        first = fake._alive_at
        for _ in range(20):
            await asyncio.sleep(0)
        task.cancel()
        return first, fake._alive_at, hung.is_set()
    finally:
        state_cycle._run_cycle, state_cycle._sleep_until_wake = real_run, real_sleep

first, later, hung = asyncio.run(turns(paused=True))
assert first is not None and later >= first and not hung                # paused: it keeps turning, no cycle started
first, later, hung = asyncio.run(turns(paused=False))
assert first is not None and later == first and hung                    # the hung cycle: no new turn after the first
print("check_healthz_loop: ok")
