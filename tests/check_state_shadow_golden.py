"""Golden-master test of DeviceState._shadow (the data per MAC for later analysis and the judgement "two different devices behind this card?"): 2500 generated situations - the
observation returning nothing, False, a job that works or fails, or raising; the judgement due or not or raising; the evaluation finding nothing, a new or an old other device or raising;
alerts enabled, disabled or failing; results with a MAC in capitals, lower case, empty, missing or an empty card; a memory of last MACs with or without the device - with the
collaborators replaced by in-memory ones that record every call must give exactly the calls (with their arguments, in order, and whether the evaluation got a COPY of the memory),
the alerts sent, the log lines of the failures, how many background tasks were created and how many are left, stored in tests/golden/state_shadow.json, written from the code as it was
before the two methods moved out of DeviceState (a digest per case plus a readable sample).
Regenerate only on purpose:  STATE_SHADOW_GOLDEN_UPDATE=1 python tests/check_state_shadow_golden.py"""
import asyncio
import hashlib
import json
import os
import random
import sys
import tempfile
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()      # never the real folder of the developer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import state as state_mod  # noqa: E402
from app.applog import logger  # noqa: E402
from app.export import mac_shadow  # noqa: E402
from app.ha import identity_shift  # noqa: E402
from app.storage import settings  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "state_shadow.json"
N = 2500
rng = random.Random(9753)
LOG: list = []
logger.debug = lambda msg, *a, **k: LOG.append(["debug", str(msg), [str(x) for x in a], bool(k.get("exc_info"))])


def pick(seq):
    return seq[rng.randrange(len(seq))]


RESULTS = [{"mac": "AA:BB:CC:00:00:01", "name": "Salotto", "ip": "10.0.0.5"}, {"mac": "aa:bb:cc:00:00:02", "ip": "10.0.0.6"}, {"mac": None, "name": None, "ip": "10.0.0.7"}, {},
           {"mac": "", "name": "", "ip": None}, {"mac": "AA:BB", "name": "", "ip": "10.0.0.8"}]


async def main():
    out = []
    for _ in range(N):
        LOG.clear()
        st = state_mod.DeviceState()
        last = {k: pick(["aa:aa", "bb:bb"]) for k in rng.sample(["d1", "d2", "d3"], rng.randrange(0, 4))}
        st._last_mac = last
        device_id = pick(["d1", "d2", "d3"])
        previous = pick([None, {"online": True}, {}])
        result = dict(pick(RESULTS))
        now = pick([1000.0, 2000.5])
        obs_mode = pick(["none", "none", "false", "job", "job", "job", "job_raises", "raise"])
        due_mode = pick(["no", "no", "yes", "yes", "yes", "raise"])
        eval_mode = pick(["none", "new", "new", "old", "raise"])
        alerts_mode = pick([True, True, True, False, "raise"])

        def observe(*args):
            LOG.append(["observe", list(args)])
            if obs_mode == "raise":
                raise RuntimeError("observe down")
            if obs_mode == "none":
                return None
            if obs_mode == "false":
                return False

            def job():
                LOG.append(["job"])
                if obs_mode == "job_raises":
                    raise OSError("job down")
            return job

        def due(device_id_, mac, now_):
            LOG.append(["due", device_id_, mac, now_])
            if due_mode == "raise":
                raise ValueError("due down")
            return due_mode == "yes"

        def evaluate(device_id_, mac, memory, now_):
            LOG.append(["evaluate", device_id_, mac, dict(memory), now_, memory is last])
            if eval_mode == "raise":
                raise RuntimeError("evaluate down")
            return {"none": None, "new": {"new": True, "k": 1}, "old": {"new": False}}[eval_mode]

        def describe(found):
            LOG.append(["describe", found])
            return "OTHER"

        def alerts_enabled():
            LOG.append(["alerts_enabled"])
            if alerts_mode == "raise":
                raise RuntimeError("settings down")
            return alerts_mode

        mac_shadow.observe, identity_shift.due, identity_shift.evaluate, identity_shift.describe = observe, due, evaluate, describe
        settings.alerts_enabled = alerts_enabled
        alerts = []
        st.emit_alert = lambda msg, key, **p: alerts.append([msg, key, p])
        before = len(st._bg)
        try:
            st._shadow(device_id, previous, result, now)
            err = None
        except Exception as exc:
            err = type(exc).__name__
        created = len(st._bg) - before
        tasks = list(st._bg)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        out.append({"err": err, "log": list(LOG), "alerts": alerts, "created": created, "bg_after": len(st._bg)})
    return out


out = asyncio.run(main())


def digest(x):
    return hashlib.sha1(json.dumps(x, default=str).encode()).hexdigest()[:20]


result = {"digests": [digest(o) for o in out], "sample": json.loads(json.dumps(out[:10], default=str))}
if os.environ.get("STATE_SHADOW_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(result, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want["digests"]) == len(result["digests"]) == N
for i, (x, y) in enumerate(zip(result["digests"], want["digests"])):
    assert x == y, "case %d differs: %s" % (i, json.dumps(out[i], default=str)[:700])
assert result["sample"] == want["sample"]
c = lambda f: sum(1 for o in out if f(o))  # noqa: E731
stats = {"tasks": c(lambda o: o["created"] == 1), "alerts": c(lambda o: o["alerts"]), "debug": c(lambda o: any(e[0] == "debug" for e in o["log"])),
         "job": c(lambda o: any(e[0] == "job" for e in o["log"])), "evaluate": c(lambda o: any(e[0] == "evaluate" for e in o["log"])),
         "no_task": c(lambda o: o["created"] == 0), "old_found": c(lambda o: any(e[0] == "describe" for e in o["log"]) is False and any(e[0] == "evaluate" for e in o["log"])),
         "empty_card": c(lambda o: any(e[0] == "evaluate" and e[2] is None for e in o["log"])), "bg_left": c(lambda o: o["bg_after"] > 0)}
for key, low in (("tasks", 800), ("alerts", 150), ("debug", 150), ("job", 300), ("evaluate", 300), ("no_task", 300), ("old_found", 100), ("empty_card", 5)):
    assert stats[key] >= low, ("scenarios too uniform", key, stats)
print("TUTTO OK")
