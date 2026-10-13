"""Reference test of the device routes (add, rename, override, delete, presence, deep rescan) through the real HTTP layer with the network faked:
what the user changes by hand on a card must be saved, refused when wrong, and tell the rest of the service (refresh, journal, ignore list)."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.ha.mqtt_ha import service as mqtt_service  # noqa: E402
from app.routes import device_routes  # noqa: E402
from app.state import state  # noqa: E402
from app.storage import blocklist, devices_config, journal  # noqa: E402
from app.storage.history import History  # noqa: E402

tmp = Path(tempfile.mkdtemp())
devices_config.DEVICES_PATH = tmp / "devices.yaml"
devices_config.CONFIG_DIR = tmp
blocklist.PATH = tmp / "ignored.json"
blocklist._cache.update(stamp=None, items=[])
journal.PATH = tmp / "journal.jsonl"
H = History(tmp / "vedetta.db")
device_routes.history = H
calls = {"refresh": [], "check": 0, "mqtt": 0}


async def fake_refresh(device_id, force=False):
    calls["refresh"].append(device_id)


async def fake_check(arp=None):
    calls["check"] += 1


state.refresh_device, state.check_new_devices = fake_refresh, fake_check
mqtt_service.refresh = lambda: calls.__setitem__("mqtt", calls["mqtt"] + 1)
app = FastAPI()
app.include_router(device_routes.router)
client = TestClient(app)
post = lambda path, body: client.post(path, json=body)   # noqa: E731

# --- add: invalid IPs are skipped, fields are cleaned, the new card is refreshed and written in the journal
r = post("/api/devices/add", {"devices": [
    {"ip": "10.0.0.5", "name": "N" * 200, "adapter": "bogus", "port": "8080", "name_source": "user",
     "scan_info": {"http_title": "T" * 500, "evil": "x", "http_server": "nginx"}},
    {"ip": "not-an-ip"}, {"ip": "10.0.0.6", "adapter": "shelly_gen1", "name_source": "nonsense"}]})
assert r.status_code == 200 and [d["ip"] for d in r.json()["added"]] == ["10.0.0.5", "10.0.0.6"], r.text
a, b = r.json()["added"]
assert len(a["name"]) == 80 and a["adapter"] == "generic" and a["port"] == 8080 and a["name_source"] == "user"
assert set(a["scan_info"]) == {"http_title", "http_server"} and len(a["scan_info"]["http_title"]) == 200
assert b["adapter"] == "shelly_gen1" and b.get("name_source") != "nonsense"
assert sorted(calls["refresh"]) == sorted([a["id"], b["id"]]) and calls["check"] == 1
assert post("/api/devices/add", {"devices": [{"ip": "10.0.0.5"}]}).json() == {"added": []}, "an address already there is not added twice"
assert post("/api/devices/add", {"devices": []}).json() == {"added": []}
A, B = a["id"], b["id"]

# --- rename: empty or wrong values refused, mobile only when a real boolean, unknown id 404
assert post(f"/api/devices/{A}/rename", {"name": "  "}).status_code == 400
assert post(f"/api/devices/{A}/rename", {"name": "x", "port": 70000}).status_code == 400
assert post(f"/api/devices/{A}/rename", {"name": "x", "port": "abc"}).status_code == 400
assert post("/api/devices/nope/rename", {"name": "x"}).status_code == 404
calls["refresh"].clear()
r = post(f"/api/devices/{A}/rename", {"name": " Kitchen TV ", "port": 9000, "mobile": True})
assert r.status_code == 200 and r.json()["name"] == "Kitchen TV" and r.json()["port"] == 9000 and calls["refresh"] == [A]
assert [d for d in devices_config.load_devices() if d["id"] == A][0].get("mobile") is True
post(f"/api/devices/{A}/rename", {"name": "Kitchen TV", "mobile": "yes"})        # not a boolean: back to automatic
assert "mobile" not in [d for d in devices_config.load_devices() if d["id"] == A][0] or [d for d in devices_config.load_devices() if d["id"] == A][0]["mobile"] is None

# --- override: unknown id, invalid type, brand set and cleared, share with HA, focus with a limit
assert post("/api/devices/nope/override", {"brand": "X"}).status_code == 404
assert post(f"/api/devices/{A}/override", {"type": "spaceship"}).status_code == 400
assert post(f"/api/devices/{A}/override", {"brand": " Philips ", "type": "media"}).json() == {"ok": True}
cfg = {d["id"]: d for d in devices_config.load_devices()}
assert cfg[A]["brand_user"] == "Philips" and cfg[A]["type_user"] == "media"
post(f"/api/devices/{A}/override", {"brand": None})
assert not {d["id"]: d for d in devices_config.load_devices()}[A].get("brand_user")
post(f"/api/devices/{A}/override", {"ha_share": True})
assert calls["mqtt"] == 1 and {d["id"]: d for d in devices_config.load_devices()}[A].get("ha_share")
assert post(f"/api/devices/{A}/override", {"focus": True, "focus_note": "odd " * 500}).json() == {"ok": True}
focused = {d["id"]: d for d in devices_config.load_devices()}[A]
assert focused.get("focus") and len(focused.get("focus_note") or "") <= devices_config.FOCUS_NOTE_MAX
post(f"/api/devices/{A}/override", {"focus": False})
assert not {d["id"]: d for d in devices_config.load_devices()}[A].get("focus")
extra = [devices_config.add_devices([{"ip": "10.0.1.%d" % i, "adapter": "generic"}])[0]["id"] for i in range(devices_config.FOCUS_MAX)]
for i in extra:
    assert post(f"/api/devices/{i}/override", {"focus": True}).status_code == 200
assert post(f"/api/devices/{A}/override", {"focus": True}).status_code == 409, "too many devices under examination"

# --- delete: unknown 404; a normal delete; delete + ignore puts the host in the ignore list first
assert client.delete("/api/devices/nope").status_code == 404
state.devices[B] = {"id": B, "ip": "10.0.0.6", "name": "10.0.0.6", "mac": "AA:BB:CC:00:00:06"}
assert client.delete(f"/api/devices/{B}?ignore=true").json() == {"ok": True}
assert B not in {d["id"] for d in devices_config.load_devices()} and B not in state.devices
assert blocklist.matches(mac="AA:BB:CC:00:00:06", ip="10.0.0.6", name=None), "the deleted device is ignored"
assert client.delete(f"/api/devices/{extra[0]}").json() == {"ok": True}

# --- presence: unknown 404, known gives the two windows
assert client.get("/api/devices/nope/presence").status_code == 404
now = time.time()
H.record_presence(A, "10.0.0.5", None, True, now - 3600)
state.devices[A] = {"id": A, "name": "Kitchen TV", "online": True, "last_seen": None}
p = client.get(f"/api/devices/{A}/presence").json()
assert p["name"] == "Kitchen TV" and p["online"] is True and set(p["windows"]) == {"24h", "7d"}, p

# --- deep rescan: only local addresses, one progress event per device, the batch is prepared once
seen = {"batch": 0, "scanned": []}


async def fake_batch(profile, ips):
    seen["batch"] += 1
    return {"profile": profile, "ips": sorted(ips)}


async def fake_rescan(d, batch):
    seen["scanned"].append((d["id"], batch["profile"]))


async def only_local(ips):
    return [i for i in ips if i != "10.0.1.1"]


device_routes.pipeline.prepare_batch, device_routes.rescan_device, device_routes.filter_local_ips = fake_batch, fake_rescan, only_local
ids = [A, extra[1], extra[2]]
ips = {d["id"]: d["ip"] for d in devices_config.load_devices()}
txt = client.post("/api/devices/rescan", json={"ids": ids}).text
events = [json.loads(l[6:]) for l in txt.splitlines() if l.startswith("data: ")]
assert events[0]["type"] == "total" and events[-1] == {"type": "complete", "rescanned": events[0]["total"]}, events
assert seen["batch"] == 1 and all(p == "deep" for _, p in seen["scanned"]) and len(seen["scanned"]) == events[0]["total"]
assert events[0]["total"] == len([i for i in ids if ips[i] != "10.0.1.1"])
print("TUTTO OK")
