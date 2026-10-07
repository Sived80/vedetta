"""The export of the window as a job over HTTP: start, follow the steps, decide what could not be fixed, take the file once; one at
a time; the period is checked; the file for the developer is sealed, the one for the person is a plain zip."""
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
from app import anonymize, devices_config, dhcp, export, export_jobs, ha_registry, mdns_listener, paths, routes_ha  # noqa: E402
from app import history as history_mod  # noqa: E402
from app.history import History  # noqa: E402
from app.state import state  # noqa: E402

tmp = Path(tempfile.mkdtemp())
paths.DATA_DIR = tmp
devices_config.DEVICES_PATH = tmp / "devices.yaml"
(tmp / "devices.yaml").write_text(yaml.safe_dump({"devices": [{"id": "d1", "ip": "192.168.77.20", "adapter": "ping", "name": "Giulia's iPad"}]}), encoding="utf-8")
(tmp / "settings.json").write_text(json.dumps({"mqtt_password": "hunter2", "mail": "c.d@example.com"}), encoding="utf-8")
(tmp / "dashboard.log").write_text("2026-10-07T10:00:00+02:00\tINFO\tstarted\n", encoding="utf-8")
H = History(tmp / "vedetta.db")
history_mod.history = H
state.devices.clear()
state.devices["d1"] = {"id": "d1", "ip": "192.168.77.20", "mac": "f0:18:98:aa:bb:cc", "name": "Giulia's iPad", "brand": "Apple", "extra": {}, "scanned_ports": [], "online": True}
dhcp.seen.clear(); mdns_listener.by_mac.clear(); mdns_listener.by_ip.clear()
ha_registry._state["by_mac"] = {}; ha_registry._state["by_ip"] = {}

app = FastAPI()
app.include_router(routes_ha.router)
c = TestClient(app)


def wait(job_id, want, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        s = c.get(f"/api/export/jobs/{job_id}").json()
        if s["status"] in want:
            return s
        time.sleep(0.05)
    raise AssertionError(f"timeout, last: {s}")


# --- the estimate
info = c.get("/api/export/info").json()
assert len(info["daily"]) == 90 and info["limit"] == 20 * 1024 * 1024 and info["horizon"] == 90 and info["base"] > 0

# --- wrong requests
assert c.post("/api/export/jobs", json={"dest": "x", "all": True}).status_code == 422
assert c.post("/api/export/jobs", json={"dest": "me", "from_day": 200, "to_day": 0}).status_code == 422       # beyond the history
assert c.post("/api/export/jobs", json={"dest": "me", "from_day": 1, "to_day": 3}).status_code == 422         # the end before the start
assert c.post("/api/export/jobs", json={"dest": "me"}).status_code == 422
assert c.get("/api/export/jobs/nope").status_code == 404

# --- for me: three steps, a plain zip, the file only once
s = c.post("/api/export/jobs", json={"dest": "me", "from_day": 1, "to_day": 0}).json()
assert s["status"] in ("running", "done") and s["dest"] == "me"
s = wait(s["id"], ("done", "error"))
assert s["status"] == "done" and s["steps"] == ["collect", "prepare", "ready"] and s["filename"].endswith(".zip") and s["size"] > 0, s
r = c.post(f"/api/export/jobs/{s['id']}/file")
assert r.status_code == 200 and r.headers["content-type"] == "application/zip" and "attachment" in r.headers["content-disposition"]
z = zipfile.ZipFile(io.BytesIO(r.content))
assert b"192.168.77.20" in z.read("state/devices_compact.json") and b"hunter2" not in z.read("data/settings.json")      # the person's data, a password still out
assert c.post(f"/api/export/jobs/{s['id']}/file").status_code == 404                                               # taken once

# --- for the developer: masked, sealed
s = wait(c.post("/api/export/jobs", json={"dest": "dev", "all": True}).json()["id"], ("done", "error", "choose"))
assert s["status"] == "done" and s["steps"] == ["collect", "mask", "check", "seal", "ready"] and s["filename"].startswith("vedetta-report-") and s["filename"].endswith(".txt"), s
r = c.post(f"/api/export/jobs/{s['id']}/file")
assert r.content.startswith(b"VEDETTA ENCRYPTED REPORT") and b"192.168.77" not in r.content and r.headers["content-type"].startswith("text/plain")

# --- one at a time
first = c.post("/api/export/jobs", json={"dest": "me", "all": True}).json()
second = c.post("/api/export/jobs", json={"dest": "me", "all": True})
assert second.status_code in (200, 409)                                   # 409 while the first one runs (it may already be over)
wait(first["id"], ("done", "error"))
c.delete(f"/api/export/jobs/{first['id']}")
assert c.get(f"/api/export/jobs/{first['id']}").status_code == 404


# --- something the masking misses: the window gets the values, the person decides, the file follows the choices
class Weak(anonymize.Anonymizer):
    def text(self, s):
        s = s.replace("c.d@example.com", "@@0@@")
        s = super().text(s)
        return s.replace("@@0@@", "c.d@example.com")


real = anonymize.Anonymizer
export.anonymize.Anonymizer = Weak
try:
    s = wait(c.post("/api/export/jobs", json={"dest": "dev", "all": True}).json()["id"], ("choose", "done", "error"))
    assert s["status"] == "choose" and s["steps"] == ["collect", "mask", "check", "fix"] and s["items_total"] == 1, s
    item = s["items"][0]
    assert item["value"] == "c.d@example.com" and item["kind"] == "email address" and item["file"] == "data/settings.json" and item["where"], item
    assert c.post(f"/api/export/jobs/{s['id']}/file").status_code == 409                    # nothing to take yet
    s2 = c.post(f"/api/export/jobs/{s['id']}/choices", json={"choices": {str(item["id"]): "rm"}}).json()
    s2 = wait(s["id"], ("done", "error"))
    assert s2["status"] == "done" and s2["steps"][-3:] == ["fix", "seal", "ready"], s2
    assert c.post(f"/api/export/jobs/{s['id']}/choices", json={"choices": {}}).status_code == 409      # decided once
finally:
    export.anonymize.Anonymizer = real
print("TUTTO OK")
