"""Characterization of adding a card with no MAC (a device behind a router), before the work on more networks:
- run_associative with a scan that finds no MAC gives "mac": None and still a name and an adapter;
- /api/devices/add never keeps a MAC from the request (the MAC is learned by the cycle), accepts a candidate without one, drops one without a valid IPv4 address and one
  already present by address, and today accepts ANY valid IPv4 address, even outside the local network (test G0-11 will turn this into a refusal with a code).
Fake scan, temporary data folder; private and documentation addresses.
    python tests/check_add_card_mac_null.py"""
import asyncio
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.routes import device_routes  # noqa: E402
from app.scan import pipeline  # noqa: E402
from app.storage import devices_config  # noqa: E402


# 1) the scan before adding: no MAC found
async def fake_batch(flow, ips):
    return type("B", (), {"mdns_names": {}})()


async def fake_scan_host(ip, batch):
    return {"ip": ip, "mac": None, "hostname": None, "ports": [{"port": 80, "proto": "tcp", "service": "http"}], "adapter": "generic", "adapter_extra": {}}


pipeline.prepare_batch = fake_batch
pipeline.scan_host = fake_scan_host
pipeline.scanner.format_scan_info = lambda info: {}
row = asyncio.run(pipeline.run_associative("10.0.20.30", name_hint="iot-camera"))
assert row["mac"] is None and row["ip"] == "10.0.20.30" and row["adapter"] == "generic", row
assert row["suggested_name"] == "iot-camera" and row["name_source"] == "mdns", row


# 2) the entry the route saves: a candidate without MAC is added, a MAC in the request is never kept
entries = [device_routes._new_device_entry(c) for c in (
    {"ip": "10.0.20.30", "name": "iot-camera"},
    {"ip": "10.0.0.10", "mac": "AA:BB:CC:00:00:0A", "name": "lamp"},
    {"ip": "not-an-ip"},
    {"ip": "203.0.113.9"},
)]
assert entries[2] is None
assert all("mac" not in e for e in entries if e), entries
added = devices_config.add_devices([e for e in entries if e])
assert [d["ip"] for d in added] == ["10.0.20.30", "10.0.0.10", "203.0.113.9"], added
assert all("mac" not in d and "last_mac" not in d for d in added), added
assert added[0]["id"] == "scan-10-0-20-30" and added[0]["name"] == "iot-camera", added[0]

# 3) the same address again is not added twice
assert devices_config.add_devices([device_routes._new_device_entry({"ip": "10.0.20.30"})]) == []
assert [d["ip"] for d in devices_config.load_devices()] == ["10.0.20.30", "10.0.0.10", "203.0.113.9"]

print("check_add_card_mac_null: ok")
