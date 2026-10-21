"""The network survey inside the export for the developer: with the tick off the export is what it always was; with it on the survey is a file of the zip, masked
(the names and addresses of the clients are told to the masking first); for the person's own export it never applies; the switch turns the whole thing off;
Home Assistant failing does not fail the export; the request is checked."""
import io
import json
import os
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app import paths  # noqa: E402
from app.export import export_engine as E, network_survey as ns  # noqa: E402
from app.ha import ha_registry  # noqa: E402
from app.routes import export_routes  # noqa: E402
from app.scan import dhcp, mdns_listener  # noqa: E402
from app.state import state  # noqa: E402
from app.storage import devices_config, history as history_mod  # noqa: E402
from app.storage.history import History  # noqa: E402

tmp = Path(tempfile.mkdtemp())
paths.DATA_DIR = tmp
devices_config.DEVICES_PATH = tmp / "devices.yaml"
(tmp / "devices.yaml").write_text(yaml.safe_dump({"devices": [{"id": "d1", "ip": "192.168.77.20", "adapter": "ping", "name": "Giulia's iPad"}]}), encoding="utf-8")
(tmp / "settings.json").write_text(json.dumps({"mqtt_password": "hunter2"}), encoding="utf-8")
history_mod.history = History(tmp / "vedetta.db")
state.devices.clear()
state.devices["d1"] = {"id": "d1", "ip": "192.168.77.20", "mac": "f0:18:98:aa:bb:cc", "name": "Giulia's iPad", "brand": "Apple", "extra": {}, "scanned_ports": [], "online": True}
dhcp.seen.clear(); mdns_listener.by_mac.clear(); mdns_listener.by_ip.clear()
ha_registry._state["by_mac"] = {}; ha_registry._state["by_ip"] = {}

SURVEY = {"version": 1, "host": {"interfaces": [{"name": "eth0", "kind": "other", "state": "up", "mac": "02:11:22:33:44:55", "ipv4": [{"address": "192.168.77.5", "prefix": 24}]}],
                                 "default_interface": "eth0", "gateway": "192.168.77.1"},
          "clients": {"count": 2, "truncated": False, "states": {"home": 1, "not_home": 1, "other": 0}, "by_platform": {"unifi": 2}, "attribute_keys": {"unifi": ["ip", "mac"]},
                      "rows": [{"platform": "unifi", "state": "home", "ip": "192.168.3.40", "mac": "aa:bb:cc:12:34:56", "host_name": "Leo-iPhone.fritz.nu"},
                               {"platform": "unifi", "state": "not_home", "ip": "192.168.50.7", "mac": "aa:bb:cc:65:43:21", "host_name": None}]},
          "integrations": {"unifi": {"trackers": 2, "disabled": 0, "entries": {"loaded": 1}}}, "hierarchy": {"devices": 3, "with_via_device": 1}}
real_collect = ns.collect
ns.collect = lambda: (SURVEY, None)


def zip_of(survey, dest="dev"):
    p = E.prepare(dest, None, None, survey=survey)
    try:
        return p, zipfile.ZipFile(io.BytesIO(E.finish(p, {})))
    finally:
        p.close()


# --- the tick off: the export is what it was (the goldens of the export say the same from the other side)
p, z = zip_of(False)
assert ns.SECTION_FILE not in z.namelist() and "survey" not in json.loads(z.read("manifest.json")) and p.survey is None

# --- the tick on, for the developer: a file, masked, with nothing left for the person to decide
p, z = zip_of(True)
assert ns.SECTION_FILE in z.namelist() and p.pending == [], p.pending
body = z.read(ns.SECTION_FILE).decode()
for real in ("Leo", "fritz.nu", "192.168.3.", "192.168.50.", "192.168.77.5", "aa:bb:cc:12:34:56", "aa:bb:cc:65:43:21", "02:11:22:33:44:55"):
    assert real not in body, real
data = json.loads(body)
assert data["clients"]["count"] == 2 and data["host"]["interfaces"][0]["name"] == "eth0" and data["hierarchy"] == {"devices": 3, "with_via_device": 1}
assert json.loads(z.read("manifest.json"))["survey"] == {"clients": 2, "interfaces": 1}

# --- for the person's own export it never applies (their data is complete already; asking changes nothing)
p, z = zip_of(True, dest="me")
assert ns.SECTION_FILE not in z.namelist() and p.survey is None

# --- the switch: off, the tick does nothing here, the route refuses, the window is told
ns.ENABLED = False
p, z = zip_of(True)
assert ns.SECTION_FILE not in z.namelist() and p.survey is None
app = FastAPI()
app.include_router(export_routes.router)
c = TestClient(app)
assert c.get("/api/export/info").json()["survey"] is False
assert c.post("/api/export/jobs", json={"dest": "dev", "all": True, "survey": True}).status_code == 422
ns.ENABLED = True
assert c.get("/api/export/info").json()["survey"] is True

# --- the request is checked
assert c.post("/api/export/jobs", json={"dest": "me", "all": True, "survey": True}).status_code == 422          # not for the person's own export
assert c.post("/api/export/jobs", json={"dest": "dev", "all": True, "survey": "yes"}).status_code == 422        # a yes or a no, nothing else


def wait(job_id):
    end = time.time() + 60
    while time.time() < end:
        s = c.get(f"/api/export/jobs/{job_id}").json()
        if s["status"] in ("done", "error", "choose"):
            return s
        time.sleep(0.05)
    raise AssertionError("timeout")


s = wait(c.post("/api/export/jobs", json={"dest": "dev", "all": True, "survey": True}).json()["id"])
assert s["status"] == "done" and s["steps"] == ["collect", "mask", "check", "seal", "ready"], s
c.post(f"/api/export/jobs/{s['id']}/file")
s = wait(c.post("/api/export/jobs", json={"dest": "dev", "all": True}).json()["id"])                                # no survey: as always
assert s["status"] == "done"
c.post(f"/api/export/jobs/{s['id']}/file")

# --- Home Assistant failing: the host part goes in, the manifest says so, the export is not lost
ns.collect = real_collect


async def refuse():
    raise ns.SurveyError("no token")


real_read = ns._read_home_assistant
ns._read_home_assistant = refuse
survey, note = ns.collect()
assert note == "Home Assistant not read (SurveyError)" and survey["clients"]["count"] == 0 and "host" in survey, (survey, note)
p, z = zip_of(True)
assert ns.SECTION_FILE in z.namelist() and any("network survey" in n for n in json.loads(z.read("manifest.json"))["notes"])
ns._read_home_assistant = real_read

# --- what Home Assistant is ever asked: only reads (the registries it already read, and the template)
assert set(ha_registry._COMMANDS.values()) == {"config/device_registry/list", "config/entity_registry/list", "config/area_registry/list", "config_entries/get"}
print("TUTTO OK")
