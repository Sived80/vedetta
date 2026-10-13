"""Golden-master test of DeviceState.poll_once (one cycle of checks: read the devices, ask the network (ARP) and measure the response times at the same time as the probes, apply every
result, forget the devices that are gone, save the latency, then follow the changed addresses, merge the duplicate phones, report the address conflicts, look for new devices and record
the MACs): 2500 generated cycles - no devices, a few, with ports; probes that work or fail; the response times failing; the ARP failing; the list of devices changed while the probes ran
(removed, moved, new); devices in memory that are gone - with every collaborator replaced by a recorder must give exactly the calls (with their arguments, in the order they happen, which
includes when the network and latency tasks are started), the log lines of the failures, whether the service was marked ready and whether an exception came out, stored in
tests/golden/state_poll.json, written from the code as it was before poll_once moved out of DeviceState (a digest per cycle plus a readable sample).
Regenerate only on purpose:  STATE_POLL_GOLDEN_UPDATE=1 python tests/check_state_poll_golden.py"""
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
from app.scan import latency, probe  # noqa: E402
from app.storage import devices_config  # noqa: E402

MODULES = [state_mod]
try:
    from app import state_cycle  # noqa: E402  (after the move poll_once lives here: the names it looks up must be replaced there too)
    MODULES.append(state_cycle)
except ImportError:
    pass

GOLDEN = Path(__file__).parent / "golden" / "state_poll.json"
N = 2500
rng = random.Random(6006)
LOG: list = []
IDS = ["d1", "d2", "d3", "d4"]
logger.error = lambda msg, *a, **k: LOG.append(["logger.error", str(msg), [str(x) for x in a]])
logger.exception = lambda msg, *a, **k: LOG.append(["logger.exception", str(msg)])


def pick(seq):
    return seq[rng.randrange(len(seq))]


def jcopy(x):
    return json.loads(json.dumps(x, default=str))


def replace_everywhere(name, value):
    for module in MODULES:
        if hasattr(module, name):
            setattr(module, name, value)


async def one_case():
    LOG.clear()
    st = state_mod.DeviceState()
    snapshot = [{"id": i, "ip": "10.0.0." + i[-1], **({"port": pick([22, 8080])} if rng.random() < 0.4 else {})} for i in rng.sample(IDS, rng.randrange(0, 5))]
    after = []
    for d in snapshot:
        roll = rng.random()
        if roll < 0.15:
            continue                                         # removed while the probes ran
        after.append({**d, "ip": "10.9.9." + d["id"][-1]} if roll < 0.3 else dict(d))
    after += [{"id": "new" + str(i), "ip": "10.1.1.1"} for i in range(rng.randrange(0, 2))]
    calls = {"load": 0}
    modes = {"probe": {d["id"]: pick(["ok", "ok", "ok", "raise"]) for d in snapshot}, "lat": pick(["ok", "ok", "ok", "raise"]), "arp": pick(["ok", "ok", "ok", "raise"])}

    def load_devices():
        calls["load"] += 1
        LOG.append(["load_devices", calls["load"]])
        return [dict(d) for d in (snapshot if calls["load"] == 1 else after)]

    def generic_titles(devices):
        LOG.append(["update_generic_titles", jcopy(devices)])

    async def probe_device(config, arp_task):
        LOG.append(["probe_device", jcopy(config), isinstance(arp_task, asyncio.Task)])
        await asyncio.sleep(0)
        if modes["probe"][config["id"]] == "raise":
            raise RuntimeError("probe down")
        return {"id": config["id"], "online": True}

    async def measure_many(items):
        LOG.append(["measure_many", jcopy(items)])
        await asyncio.sleep(0)
        if modes["lat"] == "raise":
            raise RuntimeError("latency down")
        return {d["id"]: 12.5 for d in snapshot}

    async def arp_by_ip(max_age):
        LOG.append(["arp_by_ip", max_age])
        await asyncio.sleep(0)
        if modes["arp"] == "raise":
            raise RuntimeError("arp down")
        return {"10.0.0.1": {"mac": "aa"}}

    def recorder(name, result=None):
        def f(*args):
            LOG.append([name, jcopy(list(args))])
            return result
        return f

    def async_recorder(name):
        async def f(*args):
            LOG.append([name, jcopy(list(args))])
        return f

    devices_config.load_devices = load_devices
    replace_everywhere("update_generic_titles", generic_titles)
    probe.probe_device = probe_device
    latency.measure_many = measure_many
    st._arp_by_ip = arp_by_ip
    st._apply = recorder("_apply")
    st.remove = recorder("remove")
    st._save_latency = async_recorder("_save_latency")
    st.follow_ip_changes = async_recorder("follow_ip_changes")
    st.merge_duplicate_phones = async_recorder("merge_duplicate_phones")
    st.report_ip_conflicts = recorder("report_ip_conflicts")
    st.check_new_devices = async_recorder("check_new_devices")
    st._record_macs = async_recorder("_record_macs")
    for i in rng.sample(IDS + ["old1", "old2"], rng.randrange(0, 5)):
        st.devices[i] = {"id": i}
    st._last_mac = {i: "aa:" + i for i in rng.sample(IDS, rng.randrange(0, 3))}
    try:
        await st.poll_once()
        err = None
    except Exception as exc:
        err = type(exc).__name__
    await asyncio.sleep(0)
    return {"err": err, "ready": st.ready.is_set(), "log": jcopy(LOG)}


async def main():
    return [await one_case() for _ in range(N)]


out = asyncio.run(main())


def digest(x):
    return hashlib.sha1(json.dumps(x, default=str).encode()).hexdigest()[:20]


result = {"digests": [digest(o) for o in out], "sample": jcopy(out[:6])}
if os.environ.get("STATE_POLL_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(result, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want["digests"]) == len(result["digests"]) == N
for i, (x, y) in enumerate(zip(result["digests"], want["digests"])):
    assert x == y, "cycle %d differs: %s" % (i, json.dumps(out[i], default=str)[:900])
assert result["sample"] == want["sample"]
logs = [e for o in out for e in o["log"]]
c = lambda f: sum(1 for e in logs if f(e))  # noqa: E731
stats = {"applied": c(lambda e: e[0] == "_apply"), "removed": c(lambda e: e[0] == "remove"), "probe_fail": c(lambda e: e[0] == "logger.error"), "ready": sum(1 for o in out if o["ready"]),
         "empty": sum(1 for o in out if not any(e[0] == "probe_device" for e in o["log"])), "ports": c(lambda e: e[0] == "measure_many" and any(i[2] != 80 for i in e[1])),
         "after_steps": c(lambda e: e[0] == "_record_macs"), "stale_ip": c(lambda e: e[0] == "_apply" and e[1][2].get(e[1][0]["id"]) != e[1][0])}
for key, low in (("applied", 1500), ("removed", 400), ("probe_fail", 400), ("ready", 2000), ("empty", 150), ("ports", 300), ("after_steps", 2000), ("stale_ip", 100)):
    assert stats[key] >= low, ("scenarios too uniform", key, stats)
print("TUTTO OK")
