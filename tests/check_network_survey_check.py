"""The check of the network survey: the button of the export window asks "is there anything to include?" and gets a state and a number, nothing else.
ok = router trackers found, none = Home Assistant answered and there are none, noha = Home Assistant cannot be read (no token, an error, too slow).
It never raises, it never takes long, it names no device, and the route is off when the survey is off."""
import asyncio
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.export import network_survey as ns  # noqa: E402
from app.routes import export_routes  # noqa: E402

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())

ENTITIES = [{"entity_id": "device_tracker.leo_phone", "platform": "unifi", "device_id": "d1", "disabled_by": None},
            {"entity_id": "device_tracker.guest_tv", "platform": "unifi", "device_id": "d2", "disabled_by": None},
            {"entity_id": "device_tracker.vedetta_nas", "platform": "mqtt", "device_id": "dv", "disabled_by": None}]
DEVICES = [{"id": "d1", "config_entries": ["e1"], "identifiers": [["unifi", "x"]]}, {"id": "d2", "config_entries": ["e1"], "identifiers": [["unifi", "y"]]},
           {"id": "dv", "config_entries": ["e2"], "identifiers": [["mqtt", "vedetta_nas"]]}]
ENTRIES = [{"entry_id": "e1", "domain": "unifi", "title": "Leo's router", "state": "loaded"}, {"entry_id": "e2", "domain": "mqtt", "title": "Mosquitto", "state": "loaded"}]
REG = {"entities": ENTITIES, "devices": DEVICES, "entries": ENTRIES}


def row(entity_id, ip="192.168.3.4"):
    return {"entity_id": entity_id, "state": "home", "ip": ip, "mac": "aa:bb:cc:12:34:56", "host_name": "Leo-iPhone.fritz.nu", "keys": ["ip", "mac"]}


calls = []


def answering(rows):
    async def read():
        calls.append("read")
        return REG, rows
    return read


async def failing_with(exc):
    calls.append("read")
    raise exc


async def slow():
    calls.append("read")
    await asyncio.sleep(5)


real = ns._read_home_assistant

# --- the three states
ns._read_home_assistant = answering([row("device_tracker.leo_phone"), row("device_tracker.guest_tv"), row("device_tracker.vedetta_nas")])
assert ns.check() == {"state": "ok", "clients": 2}                              # the tracker of Vedetta itself is not a client
ns._read_home_assistant = answering([])
assert ns.check() == {"state": "none", "clients": 0}
ns._read_home_assistant = answering([row("device_tracker.vedetta_nas")])
assert ns.check() == {"state": "none", "clients": 0}                            # only its own: nothing to include
for exc in (ns.SurveyError("no token"), OSError("connection refused"), RuntimeError("odd answer"), ValueError("x")):
    ns._read_home_assistant = lambda exc=exc: failing_with(exc)
    assert ns.check() == {"state": "noha", "clients": 0}, exc                   # whatever goes wrong is "cannot read", never an exception

# --- too slow: the button must not hang
ns._read_home_assistant = slow
old = ns.CHECK_TIMEOUT_S
ns.CHECK_TIMEOUT_S = 0.1
start = time.time()
assert ns.check() == {"state": "noha", "clients": 0} and time.time() - start < 2
ns.CHECK_TIMEOUT_S = old
assert 5 <= old <= 30                                                            # long enough for a slow Home Assistant, short enough for a person

# --- what the answer holds: a state and a number
ns._read_home_assistant = answering([row("device_tracker.leo_phone")])
answer = ns.check()
assert set(answer) == {"state", "clients"} and isinstance(answer["clients"], int)
text = json.dumps(answer)
for forbidden in ("Leo", "fritz.nu", "192.168", "aa:bb:cc", "unifi", "entity"):
    assert forbidden not in text, forbidden

# --- the route
app = FastAPI()
app.include_router(export_routes.router)
c = TestClient(app)
calls.clear()
ns._read_home_assistant = answering([row("device_tracker.leo_phone"), row("device_tracker.guest_tv")])
r = c.post("/api/export/survey/check")
assert r.status_code == 200 and r.json() == {"state": "ok", "clients": 2} and calls == ["read"], (r.status_code, r.text, calls)
assert c.get("/api/export/survey/check").status_code == 405                      # a read of Home Assistant is not started by a link
ns._read_home_assistant = answering([])
assert c.post("/api/export/survey/check").json() == {"state": "none", "clients": 0}
ns._read_home_assistant = lambda: failing_with(ns.SurveyError("no token"))
assert c.post("/api/export/survey/check").json() == {"state": "noha", "clients": 0}
ns.ENABLED = False
calls.clear()
assert c.post("/api/export/survey/check").status_code == 404 and calls == []     # off: no answer and Home Assistant is not even asked
ns.ENABLED = True
ns._read_home_assistant = real
print("TUTTO OK")
