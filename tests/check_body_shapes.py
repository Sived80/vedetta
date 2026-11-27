# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The routes that take a list from the body check its shape: /api/devices/add (a list of objects), /api/devices/rescan (a list of ids),
/api/scan/deep (a list of addresses and an object of name hints). A body of the wrong shape gets a translated 400, never a 500 with a traceback;
an address that is not a text (an integer is a valid IPv4Address for the standard library) is never taken as an address.
Found by the review of 1.0.1. Network faked, temporary data folder, invented addresses.
    python tests/check_body_shapes.py"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.networks import registry  # noqa: E402
from app.routes import bodies, device_routes, scan_routes  # noqa: E402
from app.scan import pipeline, scan_common  # noqa: E402
from app.storage import devices_config  # noqa: E402

tmp = Path(tempfile.mkdtemp())
devices_config.DEVICES_PATH = tmp / "devices.yaml"
devices_config.CONFIG_DIR = tmp
started = []


async def fake_allowed(ips):
    return list(ips)


registry.allowed = fake_allowed
pipeline.start_associative = lambda ips, hints: started.append((ips, hints)) or []
app = FastAPI()
app.include_router(device_routes.router)
app.include_router(scan_routes.router)
client = TestClient(app, raise_server_exceptions=False)

# 1) an integer is not an address
assert scan_common.is_valid_ipv4(3232235777) is False
assert scan_common.is_valid_ipv4("192.0.2.1") is True

# 2) bodies of the wrong shape: a client error with the translated message
BAD = [
    ("/api/devices/add", {"devices": ["x"]}), ("/api/devices/add", {"devices": 5}), ("/api/devices/add", {"devices": [1, {"ip": "192.0.2.5"}]}),
    ("/api/devices/rescan", {"ids": [[1]]}), ("/api/devices/rescan", {"ids": 5}), ("/api/devices/rescan", {"ids": [{"a": 1}]}),
    ("/api/scan/deep", {"ips": 5}), ("/api/scan/deep", {"ips": [[1]]}), ("/api/scan/deep", {"ips": [], "hints": ["x"]}),
]
# a list longer than any network Vedetta walks through (a hostile or broken client): the same 400, before any work
LIST_MAX = getattr(bodies, "LIST_MAX", 4096)
BAD += [("/api/scan/deep", {"ips": ["10.70.0.1"] * (LIST_MAX + 1)}), ("/api/devices/rescan", {"ids": ["x"] * (LIST_MAX + 1)}),
        ("/api/devices/add", {"devices": [{}] * (LIST_MAX + 1)})]
failures = []
for path, body in BAD:
    r = client.post(path, json=body)
    if r.status_code != 400 or r.json().get("detail") != "Invalid request":
        failures.append((path, str(body)[:80], r.status_code, r.text[:80]))
assert not failures, failures
assert not started, started

# 3) an integer address is dropped, not saved
r = client.post("/api/devices/add", json={"devices": [{"ip": 3232235777}]})
assert r.status_code == 200 and r.json() == {"added": [], "skipped": [{"ip": "", "reason": "invalid"}]}, (r.status_code, r.text)
assert devices_config.load_devices() == []

# 4) good bodies still pass; a hint that is not a text is left out
r = client.post("/api/scan/deep", json={"ips": ["192.0.2.7", "not-an-ip"], "hints": {"192.0.2.7": "lamp", "192.0.2.8": {"x": 1}}})
assert r.status_code == 200, (r.status_code, r.text)
assert started == [(["192.0.2.7"], {"192.0.2.7": "lamp"})], started
assert client.post("/api/devices/rescan", json={"ids": []}).status_code == 200
# a whole /22 behind the router (1022 addresses) is still a legitimate list
started.clear()
wide = [f"10.70.{n >> 8}.{n & 0xFF}" for n in range(1, 1023)]
assert client.post("/api/scan/deep", json={"ips": wide}).status_code == 200 and started[0][0] == wide
assert client.post("/api/devices/add", json={}).json() == {"added": [], "skipped": []}
print("check_body_shapes: ok")
