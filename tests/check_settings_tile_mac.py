# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The switch "MAC on the cards" (1.1.1, setting "tile_mac", asked by a user): off by default, in GET /api/settings, saved by
POST /api/settings when it is a boolean, refused (400, nothing saved) when it is not. Temporary data folder, nothing contacted.
    python tools/run_test.py check_settings_tile_mac.py"""
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.routes import settings_routes  # noqa: E402
from app.storage import settings  # noqa: E402

app = FastAPI()
app.include_router(settings_routes.router)
client = TestClient(app, raise_server_exceptions=False)
failures = []


def check(cond, msg):
    print(("ok: " if cond else "FAILED: ") + msg)
    if not cond:
        failures.append(msg)


check(settings.DEFAULTS.get("tile_mac") is False, "the default is off: nothing changes for who does not want it")
check(client.get("/api/settings").json().get("tile_mac") is False, "GET /api/settings says it")
r = client.post("/api/settings", json={"tile_mac": True})
check(r.status_code == 200 and r.json().get("tile_mac") is True, "POST true is saved: %s %s" % (r.status_code, r.text[:80]))
check(settings.load()["tile_mac"] is True, "and read back on")
for wrong in ("yes", 1, 0, None, "false"):
    r = client.post("/api/settings", json={"tile_mac": wrong})
    check(r.status_code == 400, "a value that is not a boolean is refused: %r -> %s" % (wrong, r.status_code))
check(settings.load()["tile_mac"] is True, "and nothing was saved")
r = client.post("/api/settings", json={"tile_mac": False, "group_order": []})
check(r.status_code == 200 and settings.load()["tile_mac"] is False, "POST false turns it off again")
print("ALL OK" if not failures else "%d FAILED" % len(failures))
sys.exit(1 if failures else 0)
