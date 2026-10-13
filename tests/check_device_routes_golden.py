"""Golden-master test of four device routes (add, wake, delete, deep rescan) through the real HTTP layer: 2500 generated requests - candidates with valid, invalid or missing addresses, long or
empty names, unknown adapters and name sources, wrong ports, scan info with extra or empty keys; devices with the MAC in the configuration, in the live card, in the history or only in the
history of known devices; the local network known, wrong or failing; the packet sent or not; delete with or without the ignore list, the device known or not, the removal failing; a rescan of
devices outside the local network, a batch that fails, rescans that fail - with every collaborator replaced by a recorder must give exactly the answer (status and body, the SSE stream
included) and every call made (with its arguments, in order), stored in tests/golden/device_routes.json, written from the code as it was before the four handlers were split into small
functions (a digest per request plus a readable sample).
Regenerate only on purpose:  DEVICE_ROUTES_GOLDEN_UPDATE=1 python tests/check_device_routes_golden.py"""
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
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.applog import logger  # noqa: E402
from app.routes import device_routes  # noqa: E402
from app.routes.scan_routes import SCAN_INFO_KEYS  # noqa: E402
from app.scan import pipeline, scanner, wol  # noqa: E402
from app.state import state  # noqa: E402
from app.storage import blocklist, devices_config, journal  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "device_routes.json"
N = 2500
rng = random.Random(1212)
LOG: list = []
IDS = ["d1", "d2", "d3"]
MACS = ["aa:bb:cc:dd:ee:01", "aa:bb:cc:dd:ee:02", "not a mac", "", None]


def pick(seq):
    return seq[rng.randrange(len(seq))]


def jcopy(x):
    return json.loads(json.dumps(x, default=str))


def rec(name, result=None):
    def f(*args, **kwargs):
        LOG.append([name, jcopy(list(args)), jcopy(kwargs)])
        return result
    return f


logger.info = lambda msg, *a, **k: LOG.append(["info", str(msg), [str(x) for x in a]])
logger.exception = lambda msg, *a, **k: LOG.append(["exception", str(msg), [str(x) for x in a]])
journal.add = rec("journal.add")
state.remove = rec("state.remove")
state.rescan_started = rec("rescan_started")
state.rescan_finished = rec("rescan_finished")
state.track = lambda task: LOG.append(["track"])
device_routes._watch_wake = lambda device_id: (LOG.append(["_watch_wake", device_id]), _noop())[1]


async def _noop():
    return None


async def refresh_device(device_id, force=False):
    LOG.append(["refresh_device", device_id])


async def check_new_devices(arp=None):
    LOG.append(["check_new_devices"])


state.refresh_device, state.check_new_devices = refresh_device, check_new_devices
app = FastAPI()
app.include_router(device_routes.router)
client = TestClient(app, raise_server_exceptions=False)
M: dict = {}


def configure(**kw):
    M.clear()
    M.update(kw)


async def fake_local_network():
    LOG.append(["get_local_network"])
    if M["net"] == "raise":
        raise RuntimeError("no network")
    return {"ok": ("192.168.1.0/24", "192.168.1.5"), "bad": ("not a subnet", "192.168.1.5")}[M["net"]]


async def fake_filter_local_ips(ips):
    LOG.append(["filter_local_ips", list(ips)])
    if M["local"] == "raise":
        raise RuntimeError("filter down")
    return [ip for i, ip in enumerate(ips) if M["local"] == "all" or i % 2 == 0]


async def fake_prepare_batch(profile, ips):
    LOG.append(["prepare_batch", profile, list(ips)])
    if M["batch"] == "raise":
        raise RuntimeError("batch down")
    return {"batch": True}


async def fake_rescan_device(d, batch):
    LOG.append(["rescan_device", d["id"], batch])
    for _ in range(IDS.index(d["id"]) + 1):         # a fixed finishing order: as_completed has none when several finish together
        await asyncio.sleep(0)
    if M["rescan"].get(d["id"]) == "raise":
        raise RuntimeError("rescan down")


class FakeHistory:
    def last_mac(self, device_id):
        LOG.append(["history.last_mac", device_id])
        return M["last_mac"]

    def known_all(self):
        LOG.append(["history.known_all"])
        return {m: {"ip": ip} for m, ip in M["known"]}


def configs():
    return [{"id": i, "ip": "10.0.0." + i[-1], **({"name": "Name " + i} if rng.random() < 0.6 else {}), **({"mac": pick(MACS)} if rng.random() < 0.5 else {})} for i in rng.sample(IDS, rng.randrange(0, 4))]


def fake_load(configs_):
    def f():
        LOG.append(["load_devices"])
        return [dict(c) for c in configs_]
    return f


device_routes.history = FakeHistory()
device_routes.get_local_network, device_routes.filter_local_ips, device_routes.rescan_device = fake_local_network, fake_filter_local_ips, fake_rescan_device
pipeline.prepare_batch = fake_prepare_batch
wol.send = lambda mac, targets: (LOG.append(["wol.send", mac, list(targets)]), M["sent"])[1]
blocklist.add_host = rec("blocklist.add_host")


def case_add():
    cands = []
    for _ in range(rng.randrange(0, 4)):
        c = {}
        if rng.random() < 0.85:
            c["ip"] = pick(["10.0.0.5", "10.0.0.6", "not-an-ip", "", "999.1.1.1"])
        if rng.random() < 0.5:
            c["adapter"] = pick(["shelly_gen1", "generic", "bogus", None])
        if rng.random() < 0.5:
            c["name"] = pick(["Salotto", "N" * 200, "", None, 5])
        if rng.random() < 0.5:
            c["name_source"] = pick(["user", "mdns", "dhcp", "bogus", None])
        if rng.random() < 0.4:
            c["port"] = pick(["8080", 0, None, 22, "x"])
        if rng.random() < 0.5:
            c["scan_info"] = pick([{k: pick(["v", "T" * 300, "", None]) for k in rng.sample(list(SCAN_INFO_KEYS) + ["evil"], rng.randrange(0, 4))}, "text", None, []])
        cands.append(c)
    body = pick([{"devices": cands}] * 8 + [{}, []])
    mode = pick(["ok", "ok", "ok", "empty", "raise"])
    configure(add=mode)

    def add_devices(entries):
        LOG.append(["add_devices", jcopy(entries)])
        if M["add"] == "raise":
            raise RuntimeError("disk full")
        if M["add"] == "empty":
            return []
        return [{**e, "id": "id-" + e["ip"], "name": e.get("name")} for e in entries]

    devices_config.add_devices = add_devices
    r = client.post("/api/devices/add", json=body)
    return ["add", body, r]


def case_wake():
    cfgs = configs()
    device_id = pick(IDS + ["ghost"])
    state.devices.clear()
    if rng.random() < 0.6:
        state.devices[device_id] = {"mac": pick(MACS), "online": True}
    configure(last_mac=pick(MACS), known=[(pick(MACS), pick(["10.0.0.1", "10.0.0.2", "10.0.0.3"])) for _ in range(rng.randrange(0, 3))], net=pick(["ok", "ok", "bad", "raise"]), sent=pick([True, True, False]))
    devices_config.load_devices = fake_load(cfgs)
    r = client.post("/api/devices/%s/wake" % device_id)
    return ["wake", [device_id, cfgs], r]


def case_delete():
    cfgs = configs()
    device_id = pick(IDS + ["ghost"])
    state.devices.clear()
    if rng.random() < 0.7:
        ip = pick(["10.0.0.1", "10.0.0.2", None])
        state.devices[device_id] = {k: v for k, v in {"name": pick([ip, "Salotto", None]), "ip": ip, "mac": pick(MACS)}.items() if rng.random() < 0.85}
    state._last_mac = {device_id: pick(MACS)} if rng.random() < 0.5 else {}
    configure(remove=pick(["ok", "ok", "none", "raise"]))

    def remove_device(did):
        LOG.append(["remove_device", did])
        if M["remove"] == "raise":
            raise RuntimeError("cannot write")
        return None if M["remove"] == "none" else {"id": did}

    devices_config.remove_device = remove_device
    ignore = pick([True, False, False])
    r = client.delete("/api/devices/%s?ignore=%s" % (device_id, "true" if ignore else "false"))
    return ["delete", [device_id, ignore], r]


def case_rescan():
    cfgs = configs()
    ids = [c["id"] for c in cfgs if rng.random() < 0.7] + ([pick(["ghost", "d9"])] if rng.random() < 0.2 else [])
    body = pick([{"ids": ids}] * 8 + [{}])
    configure(local=pick(["all", "half", "half", "raise"]), batch=pick(["ok", "ok", "ok", "raise"]), rescan={c["id"]: pick(["ok", "ok", "raise"]) for c in cfgs})
    devices_config.load_devices = fake_load(cfgs)
    r = client.post("/api/devices/rescan", json=body)
    return ["rescan", body, r]


out = []
for _ in range(N):
    LOG.clear()
    kind, req, r = pick([case_add, case_add, case_wake, case_wake, case_wake, case_delete, case_delete, case_rescan])()
    out.append({"kind": kind, "req": jcopy(req), "status": r.status_code, "body": r.text[:2500], "log": jcopy(LOG)})


def digest(x):
    return hashlib.sha1(json.dumps(x, default=str).encode()).hexdigest()[:20]


result = {"digests": [digest(o) for o in out], "sample": jcopy(out[:8])}
if os.environ.get("DEVICE_ROUTES_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(result, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want["digests"]) == len(result["digests"]) == N
for i, (x, y) in enumerate(zip(result["digests"], want["digests"])):
    assert x == y, "request %d differs: %s" % (i, json.dumps(out[i], default=str)[:900])
assert result["sample"] == want["sample"]
c = lambda f: sum(1 for o in out if f(o))  # noqa: E731
st = lambda k, code: c(lambda o: o["kind"] == k and o["status"] == code)  # noqa: E731
stats = {"add200": st("add", 200), "add500": st("add", 500), "wake200": st("wake", 200), "wake400": st("wake", 400), "wake404": st("wake", 404), "wake500": st("wake", 500), "del200": st("delete", 200),
         "del404": st("delete", 404), "del500": st("delete", 500), "resc200": st("rescan", 200), "resc500": st("rescan", 500),
         "added": c(lambda o: o["kind"] == "add" and '"added":[{' in o["body"].replace(" ", "")), "blocked": c(lambda o: any(e[0] == "blocklist.add_host" for e in o["log"])),
         "targets2": c(lambda o: any(e[0] == "wol.send" and len(e[2]) == 2 for e in o["log"])), "streamed": c(lambda o: o["kind"] == "rescan" and "complete" in o["body"]),
         "via_history": c(lambda o: any(e[0] == "history.known_all" for e in o["log"]))}
for key, low in (("add200", 400), ("add500", 30), ("wake200", 150), ("wake400", 100), ("wake404", 100), ("wake500", 20), ("del200", 200), ("del404", 80), ("del500", 30), ("resc200", 100), ("resc500", 15),
                 ("added", 60), ("blocked", 40), ("targets2", 80), ("streamed", 100), ("via_history", 100)):
    assert stats[key] >= low, ("scenarios too uniform", key, stats)
print("TUTTO OK")
