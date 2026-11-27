# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""R8 (two public reports): "Add all" must say what it did not add and why. POST /api/devices/add answers, next to the cards it made, every candidate it
left out with a reason the page can show: "exists" (a card already has that address, or the same address came twice), "invalid" (not an IPv4 address),
"off_limits" (an address no card may have: a paused network, a public or container address, K9a). Before, the route answered only the cards made and the
page showed every row as added. Invented addresses only.
    python tests/check_add_tells_skipped.py"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()      # never the real folder of the developer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app import netutil  # noqa: E402
from app.routes import device_routes  # noqa: E402
from app.state import state  # noqa: E402
from app.storage import devices_config, journal  # noqa: E402

tmp = Path(os.environ["VEDETTA_DATA_DIR"])
devices_config.DEVICES_PATH = tmp / "devices.yaml"
devices_config.CONFIG_DIR = tmp
journal.PATH = tmp / "journal.jsonl"


async def fake_refresh(device_id, force=False):
    return None


async def fake_check(arp=None):
    return None


state.refresh_device, state.check_new_devices = fake_refresh, fake_check
netutil.last_network = "192.0.2.0/24"          # the main network as last read (never the machine's own)
app = FastAPI()
app.include_router(device_routes.router)
client = TestClient(app)


def add(*ips):
    r = client.post("/api/devices/add", json={"devices": [{"ip": ip} for ip in ips]})
    assert r.status_code == 200, r.text
    return r.json()


first = add("192.0.2.10")
assert [d["ip"] for d in first["added"]] == ["192.0.2.10"], first
assert first.get("skipped") == [], "nothing left out: an empty list, so the page can count on it: %s" % first

got = add("192.0.2.10", "192.0.2.11", "192.0.2.11", "not-an-ip", "8.8.8.8", "192.0.2.12")
assert [d["ip"] for d in got["added"]] == ["192.0.2.11", "192.0.2.12"], got
skipped = got.get("skipped")
assert skipped == [
    {"ip": "192.0.2.10", "reason": "exists"},
    {"ip": "192.0.2.11", "reason": "exists"},
    {"ip": "not-an-ip", "reason": "invalid"},
    {"ip": "8.8.8.8", "reason": "off_limits"},
], "every candidate left out comes back with its reason, in the order sent: %s" % skipped

odd = client.post("/api/devices/add", json={"devices": [{"name": "no address"}, {"ip": 5}]}).json()
assert odd["added"] == [] and [s["reason"] for s in odd["skipped"]] == ["invalid", "invalid"] and all(s["ip"] == "" for s in odd["skipped"]), odd
print("ALL OK")
