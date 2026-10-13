"""Golden-master test of DeviceState._loop (the periodic cycle: wait the minimum gap when a cycle was woken by an event, note the start, run poll_once - a failure is logged and the service
marked ready, a cancellation goes out -, note the end, then wait for the interval or for a wake-up, while paused only until the pause ends): 2500 generated runs - the loop paused or not
(also with no end, 0 or a few seconds left), forced or not, woken by the timer or by an event with or without a reason, a cycle that works, fails or is cancelled, the interval from the
settings or the default when they fail, the clock moved only by the waits - with the waits (asyncio.sleep, asyncio.wait_for), the clock and the collaborators replaced by recorders that follow
a script and end the loop with a cancellation must give exactly the calls (with their arguments, in order), the events sent, the log of the failures and the state left (_cause, _wake_reason,
_next_at, _last_start, _force, ready), stored in tests/golden/state_loop.json, written from the code as it was before _loop moved out of DeviceState (a digest per run plus a readable sample).
Regenerate only on purpose:  STATE_LOOP_GOLDEN_UPDATE=1 python tests/check_state_loop_golden.py"""
import asyncio
import hashlib
import json
import os
import random
import sys
import tempfile
import time
import types
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()      # never the real folder of the developer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import state as state_mod  # noqa: E402
from app.applog import logger  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "state_loop.json"
N = 2500
rng = random.Random(3113)
LOG: list = []
CLOCK = [1000.0]
logger.exception = lambda msg, *a, **k: LOG.append(["logger.exception", str(msg)])
real_wait_for, real_sleep, real_monotonic = asyncio.wait_for, asyncio.sleep, time.monotonic


def pick(seq):
    return seq[rng.randrange(len(seq))]


def jcopy(x):
    return json.loads(json.dumps(x, default=str))


async def one_run():
    LOG.clear()
    CLOCK[0] = pick([1000.0, 50000.0])
    st = state_mod.DeviceState()
    events = []
    st.emit_event = lambda event: events.append(jcopy(event))
    inf = float("inf")
    left = {"v": pick([None, None, None, 0.0, 3.0, 50.0, inf])}
    st._pause = types.SimpleNamespace(remaining=lambda: left["v"], total=pick([0, 60.0]))
    st._force = rng.random() < 0.25
    st._cause = pick(["", "", "ip", "other"])
    st._wake_reason = pick(["", "mqtt"])
    st._last_start = CLOCK[0] - pick([0.0, 3.0, 9.5, 10.0, 200.0])
    interval_mode = pick(["ok", "ok", "ok", "raise"])
    state_mod.settings = types.SimpleNamespace(poll_interval=lambda: (_ for _ in ()).throw(RuntimeError("settings")) if interval_mode == "raise" else pick([10, 30, 300]),
                                               DEFAULTS={"poll_interval": 30})
    st._note_start = lambda cause: LOG.append(["note_start", cause])
    st._note_end = lambda started: LOG.append(["note_end", started])
    poll_modes = [pick(["ok", "ok", "ok", "raise", "cancel"]) for _ in range(8)]
    polls = []

    async def poll_once():
        i = len(polls)
        polls.append(1)
        LOG.append(["poll_once", i, st.ready.is_set(), st._wake.is_set()])
        mode = poll_modes[i]
        if mode == "raise":
            raise RuntimeError("cycle down")
        if mode == "cancel":
            raise asyncio.CancelledError()

    st.poll_once = poll_once
    script = [pick(["wake", "timeout", "timeout", "wake"]) for _ in range(rng.randrange(1, 6))] + ["end"]

    async def fake_wait_for(awaitable, timeout):
        awaitable.close()                                  # the coroutine of Event.wait() is never awaited here
        outcome = script.pop(0)
        LOG.append(["wait_for", timeout, outcome, CLOCK[0]])
        CLOCK[0] += pick([0.0, 1.5, 12.0])
        left["v"] = pick([None, None, 0.0, 3.0, 50.0, inf])
        if outcome == "end":
            raise asyncio.CancelledError()
        if outcome == "timeout":
            raise asyncio.TimeoutError()
        st._wake_reason = pick(["", "ip", "mqtt"])
        st._force = rng.random() < 0.2
        st._wake.set()                                     # what a real wake-up leaves behind: the loop must clear it before the next cycle
        return True

    async def fake_sleep(seconds):
        LOG.append(["sleep", seconds])
        CLOCK[0] += seconds

    asyncio.wait_for, asyncio.sleep, time.monotonic = fake_wait_for, fake_sleep, lambda: CLOCK[0]
    try:
        await st._loop()
        ended = "returned"
    except asyncio.CancelledError:
        ended = "cancelled"
    except Exception as exc:
        ended = type(exc).__name__
    finally:
        asyncio.wait_for, asyncio.sleep, time.monotonic = real_wait_for, real_sleep, real_monotonic
    return {"ended": ended, "ready": st.ready.is_set(), "log": jcopy(LOG), "events": events, "cause": st._cause, "wake_reason": st._wake_reason, "next_at": st._next_at,
            "last_start": st._last_start, "force": st._force, "wake_set": st._wake.is_set()}


async def main():
    return [await one_run() for _ in range(N)]


out = asyncio.run(main())


def digest(x):
    return hashlib.sha1(json.dumps(x, default=str).encode()).hexdigest()[:20]


result = {"digests": [digest(o) for o in out], "sample": jcopy(out[:6])}
if os.environ.get("STATE_LOOP_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(result, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want["digests"]) == len(result["digests"]) == N
for i, (x, y) in enumerate(zip(result["digests"], want["digests"])):
    assert x == y, "run %d differs: %s" % (i, json.dumps(out[i], default=str)[:900])
assert result["sample"] == want["sample"]
logs = [e for o in out for e in o["log"]]
c = lambda f: sum(1 for e in logs if f(e))  # noqa: E731
stats = {"sleeps": c(lambda e: e[0] == "sleep"), "polls": c(lambda e: e[0] == "poll_once"), "failed": c(lambda e: e[0] == "logger.exception"),
         "forced_note": c(lambda e: e[0] == "note_start" and e[1] == "force"), "event_note": c(lambda e: e[0] == "note_start" and e[1] in ("ip", "other", "mqtt")),
         "timer_note": c(lambda e: e[0] == "note_start" and e[1] == ""), "timeouts": c(lambda e: e[0] == "wait_for" and e[2] == "timeout"), "wakes": c(lambda e: e[0] == "wait_for" and e[2] == "wake"),
         "cancelled_poll": sum(1 for o in out if o["ended"] == "cancelled" and not any(e[0] == "wait_for" and e[2] == "end" for e in o["log"])),
         "paused_ready": sum(1 for o in out if o["ready"] and not any(e[0] == "poll_once" for e in o["log"])), "short_wait": c(lambda e: e[0] == "wait_for" and e[1] < 10 and e[1] != 30)}
for key, low in (("sleeps", 300), ("polls", 3000), ("failed", 500), ("forced_note", 150), ("event_note", 800), ("timer_note", 800), ("timeouts", 1500), ("wakes", 1500), ("cancelled_poll", 100),
                 ("paused_ready", 150), ("short_wait", 150)):
    assert stats[key] >= low, ("scenarios too uniform", key, stats)
print("TUTTO OK")
