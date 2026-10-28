"""Golden-master test of DeviceState._apply (the decision of a checked device: stale result, automatic name, MAC memory, shadow work, online/offline with the tolerance to missed checks,
last seen, response time, event only when something changed or when forced): 2500 generated sequences of results - online or offline (also from a device already online, within and beyond the
limit of misses), observed fields present or not, extra data, MAC in capitals/empty/missing, automatic names (with force, falsy, empty), configurations that are the same, changed or missing,
force on or off - with the clock, the response time tracker, the shadow work, the presence writing, the automatic name and the event bus replaced by recorders must give exactly the stored
devices, the revision, the revision of each device, the tombstones, the misses and last-seen memories, the events sent, the result as it was left and every call made (with its arguments, in
order), stored in tests/golden/state_apply.json, written from the code as it was before _apply was split (a digest per sequence plus a readable sample).
Regenerate only on purpose:  STATE_APPLY_GOLDEN_UPDATE=1 python tests/check_state_apply_golden.py"""
import copy
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
from app.scan import latency  # noqa: E402
from app.storage import devices_config  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "state_apply.json"
N = 2500
rng = random.Random(4242)
LOG: list = []
CLOCK = [5000.0]
time.time = lambda: CLOCK[0]
IDS = ["d1", "d2"]
OBS = list(state_mod._OBSERVED)


def pick(seq):
    return seq[rng.randrange(len(seq))]


def jcopy(x):
    return json.loads(json.dumps(x, default=str))


latency.tracker.add = lambda device_id, sample: LOG.append(["tracker.add", device_id, sample])
latency.tracker.reset = lambda device_id: LOG.append(["tracker.reset", device_id])
VALUES = {}


def tracker_value(device_id):
    LOG.append(["tracker.value", device_id])
    return VALUES.get(device_id)


latency.tracker.value = tracker_value
devices_config.update_auto_name = lambda device_id, name, source, force=False, mac=None: LOG.append(["update_auto_name", device_id, name, source, force])


def make_result(device_id, online=None):
    r = {"id": device_id, "online": rng.random() < 0.5 if online is None else online, "ip": pick(["10.0.0.5", "10.0.0.6"]),
         "extra": {pick(["a", "b", "c"]): pick([1, 2, "x"]) for _ in range(rng.randrange(0, 3))}}
    for k in rng.sample(OBS, rng.randrange(0, 6)):
        r[k] = pick([None, "v1", 7])
    if rng.random() < 0.75:
        r["mac"] = pick(["aa:bb", "AA:BB", "", None])
    if rng.random() < 0.3:
        r["auto_name"] = pick([("N", "src"), ("N", "src", True), ("N", "src", 0), ("N", "src", None), ()])
    return r


def case():
    LOG.clear()
    CLOCK[0] = pick([5000.0, 90000.5])
    st = state_mod.DeviceState()
    events = []
    st.emit_event = lambda event: events.append(jcopy(event))
    st._record_presence = lambda result, online, ts: LOG.append(["record_presence", result["id"], online, ts])
    st._shadow = lambda device_id, previous, result, now: LOG.append(["shadow", device_id, jcopy(previous), jcopy(result), now])
    limit = pick([1, 2, 3])
    state_mod.settings = types.SimpleNamespace(miss_limit=lambda: limit, poll_interval=lambda: 30, DEFAULTS={"poll_interval": 30})
    for i in rng.sample(IDS, rng.randrange(0, 3)):
        st.devices[i] = {**make_result(i, online=True), "last_seen": None, "latency_ms": 10, "latency_color": "green"} if rng.random() < 0.9 else {}      # {}: a stored card with nothing in it
    for i in rng.sample(IDS, rng.randrange(0, 3)):
        st._removed[i] = pick([1, 2])                                                                                                  # a device removed a moment ago
    for i in rng.sample(IDS, rng.randrange(0, 3)):
        st._misses[i] = pick([0, 1, 2])
        st._last_seen[i] = pick([4000.0, 4900.5])
    steps = []
    last_raw: dict = {}
    for _ in range(rng.randrange(1, 9)):
        device_id = pick(IDS)
        config = {"id": device_id, "ip": "10.0.0." + device_id[-1]}
        current = pick([{device_id: config}] * 6 + [{device_id: {**config, "ip": "9.9.9.9"}}, {}])
        if device_id in last_raw and rng.random() < 0.35:      # the same raw result again: nothing changed, so no event unless forced
            result = copy.deepcopy(last_raw[device_id])
        else:
            result = make_result(device_id)
            VALUES[device_id] = pick([None, 20, 150, 900])
        last_raw[device_id] = copy.deepcopy(result)
        sample = pick([None, 12.5, 80])
        force = rng.random() < 0.25
        CLOCK[0] += pick([0.0, 1.5, 40.0])
        try:
            st._apply(config, result, current, sample, force=force)
            err = None
        except Exception as exc:
            err = type(exc).__name__
        steps.append({"err": err, "result": jcopy(result), "devices": jcopy(st.devices), "rev": st.rev, "rev_of": dict(st._rev_of), "removed": dict(st._removed),
                      "misses": dict(st._misses), "last_seen": dict(st._last_seen), "last_mac": dict(st._last_mac), "events": len(events), "calls": len(LOG)})
    return {"steps": steps, "events": events, "log": jcopy(LOG)}


out = [case() for _ in range(N)]


def digest(x):
    return hashlib.sha1(json.dumps(x, default=str).encode()).hexdigest()[:20]


result = {"digests": [digest(o) for o in out], "sample": jcopy(out[:6])}
if os.environ.get("STATE_APPLY_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(result, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want["digests"]) == len(result["digests"]) == N
for i, (x, y) in enumerate(zip(result["digests"], want["digests"])):
    assert x == y, "sequence %d differs: %s" % (i, json.dumps(out[i], default=str)[:800])
assert result["sample"] == want["sample"]
logs = [e for o in out for e in o["log"]]
steps = [s for o in out for s in o["steps"]]
c = lambda f, seq: sum(1 for x in seq if f(x))  # noqa: E731
stats = {"shadow": c(lambda e: e[0] == "shadow", logs), "auto": c(lambda e: e[0] == "update_auto_name", logs), "auto_forced": c(lambda e: e[0] == "update_auto_name" and e[4] is True, logs),
         "reset": c(lambda e: e[0] == "tracker.reset", logs), "add": c(lambda e: e[0] == "tracker.add", logs), "rec_off": c(lambda e: e[0] == "record_presence" and e[2] is False, logs),
         "rec_on": c(lambda e: e[0] == "record_presence" and e[2] is True, logs), "events": sum(len(o["events"]) for o in out), "errors": c(lambda s: s["err"], steps),
         "tolerated": c(lambda s: s["result"].get("online") is True and s["result"].get("last_seen") is None and any(m > 0 for m in s["misses"].values()), steps),
         "noop": sum(1 for o in out for a, b in zip(o["steps"], o["steps"][1:]) if b["events"] == a["events"] and b["calls"] > a["calls"]),      # worked, nothing changed, no event
         "stale": sum(1 for o in out for a, b in zip(o["steps"], o["steps"][1:]) if b["events"] == a["events"] and b["calls"] == a["calls"] and b["devices"] == a["devices"])}
for key, low in (("shadow", 800), ("auto", 400), ("auto_forced", 100), ("reset", 800), ("add", 800), ("rec_off", 400), ("rec_on", 800), ("events", 3000), ("tolerated", 300), ("noop", 300), ("stale", 100)):
    assert stats[key] >= low, ("scenarios too uniform", key, stats)
print("TUTTO OK")
