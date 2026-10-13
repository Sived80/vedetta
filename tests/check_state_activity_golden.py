"""Golden-master test of the activities in progress of DeviceState (the scans and searches shown by the blinking LED and the search button): 2500 generated sequences of
operations - rescan_started with lists of ids (empty, repeated), rescan_finished (also of an id that is not there), search_started, search_finished (also more often than started),
activity_info, a changed revision, the clock moving (also exactly to the end of the 2.5 s hold) and the delayed notices being fired - with the clock frozen and the event bus replaced
must give exactly the events sent, the delayed calls asked for (delay and what they call), the state seen through rescanning, _search_running and _search_hold_until, and
activity_info after every step, stored in tests/golden/state_activity.json, written from the code as it was before the activities moved out of DeviceState (a digest per
sequence plus a readable sample).
Regenerate only on purpose:  STATE_ACTIVITY_GOLDEN_UPDATE=1 python tests/check_state_activity_golden.py"""
import asyncio
import hashlib
import json
import os
import random
import sys
import tempfile
import time
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()      # never the real folder of the developer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import state as state_mod  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "state_activity.json"
N = 2500
rng = random.Random(5150)
CLOCK = [100.0]
time.monotonic = lambda: CLOCK[0]
IDS = ["d1", "d2", "d3", "d10"]


def pick(seq):
    return seq[rng.randrange(len(seq))]


def held(st):
    """(rescanning, searches running, end of the hold) wherever the code keeps them: on DeviceState itself or on its activity object."""
    a = getattr(st, "_activity", None)
    if a is None:
        return sorted(st.rescanning), st._search_running, st._search_hold_until
    return sorted(a.rescanning), a.search_running, a.search_hold_until


def sequence(st, pending, events, calls):
    steps = []
    for _ in range(rng.randrange(1, 14)):
        op = pick(["rs", "rs", "rf", "rf", "ss", "ss", "sf", "sf", "sf", "info", "info", "adv", "adv", "rev", "fire"])
        arg = None
        try:
            if op == "rs":
                arg = rng.sample(IDS, rng.randrange(0, 4)) + ([pick(IDS)] if rng.random() < 0.2 else [])
                st.rescan_started(arg)
            elif op == "rf":
                arg = pick(IDS + ["ghost"])
                st.rescan_finished(arg)
            elif op == "ss":
                st.search_started()
            elif op == "sf":
                st.search_finished()
            elif op == "info":
                pass
            elif op == "adv":
                arg = pick([0.0, 0.5, 2.0, 2.5, 3.0])
                CLOCK[0] += arg
            elif op == "rev":
                arg = pick([0, 3, 41])
                st.rev = arg
            elif op == "fire":
                cbs = list(pending)
                pending.clear()
                for cb in cbs:
                    cb()
            err = None
        except Exception as exc:
            err = type(exc).__name__
        steps.append([op, arg, err, *held(st), st.activity_info(), len(events), len(calls), CLOCK[0]])
    return steps


async def main():
    loop = asyncio.get_running_loop()
    pending, calls = [], []

    def call_later(delay, callback, *args):
        calls.append(["call_later", delay, getattr(callback, "__name__", "?")])
        pending.append(callback)

    loop.call_later = call_later
    out = []
    for _ in range(N):
        CLOCK[0] = pick([100.0, 5000.0])
        events, calls_len = [], 0
        calls.clear()
        pending.clear()
        st = state_mod.DeviceState()
        st.emit_event = events.append
        steps = sequence(st, pending, events, calls)
        out.append({"steps": steps, "events": events, "calls": list(calls), "rescanning": held(st)[0], "running": held(st)[1]})
    return out


out = asyncio.run(main())


def digest(x):
    return hashlib.sha1(json.dumps(x, default=str).encode()).hexdigest()[:20]


result = {"digests": [digest(o) for o in out], "sample": json.loads(json.dumps(out[:8], default=str))}
if os.environ.get("STATE_ACTIVITY_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(result, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want["digests"]) == len(result["digests"]) == N
for i, (x, y) in enumerate(zip(result["digests"], want["digests"])):
    assert x == y, "sequence %d differs: %s" % (i, json.dumps(out[i], default=str)[:700])
assert result["sample"] == want["sample"]
steps = [s for o in out for s in o["steps"]]
hold = sum(1 for s in steps if s[0] == "info" and s[6]["search"] and s[4] == 0)
clamp = sum(1 for o in out for i, s in enumerate(o["steps"]) if s[0] == "sf" and s[4] == 0)
boundary = sum(1 for s in steps if s[0] == "info" and s[4] == 0 and s[5] == s[9])      # asked exactly when the 2.5 s hold ends
calls_n = sum(len(o["calls"]) for o in out)
fired = sum(1 for o in out for e in o["events"] if e.get("type") == "activity")
for key, val, low in (("hold", hold, 150), ("clamp", clamp, 300), ("calls", calls_n, 600), ("events", fired, 3000), ("boundary", boundary, 20)):
    assert val >= low, ("scenarios too uniform", key, val)
print("TUTTO OK")
