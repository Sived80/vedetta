"""Ports and bodies that come from outside are validated in ONE place each. Found by the global review: the port of a card was taken as it came (a Shelly added with port 9100 received a GET every
cycle: the generic adapter refused no-talk ports, the Shelly ones did not), the body of a modifying request was used as a dictionary without checking (an empty list gave a 500 with a traceback in the log),
and the port of the MQTT broker could be a printing port. Rule: never risk commanding a device."""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import httpx  # noqa: E402
from app.routes import device_routes  # noqa: E402
from app.scan import scan_common  # noqa: E402
from app.scan.adapters import shelly_gen1, shelly_gen2  # noqa: E402
from app.storage import devices_config as dc  # noqa: E402

tmp = Path(tempfile.mkdtemp())
dc.CONFIG_DIR = tmp
dc.DEVICES_PATH = tmp / "devices.yaml"

# 1) the validator: numbers and digit strings from 1 to 65535, never a no-talk port, never a bool or a float
valid = scan_common.valid_port
assert valid(80) == 80 and valid("8080") == 8080 and valid(65535) == 65535 and valid(" 443 ") == 443
for bad in (0, -1, 65536, 99999, "abc", "0x1f4", "80.5", 80.5, True, None, "", [80], {"p": 80}):
    assert valid(bad) is None, bad
for port in (9100, 9107, 515, 502, 102, 44818, "9100", "502"):
    assert valid(port) is None, port

# 2) the Shelly adapters never connect to a no-talk port (the generic one already did not)
opened: list = []


class Spy:
    def __init__(self, *a, **k):
        opened.append(1)
        raise httpx.ConnectError("spy: no network in this test")


real_client = httpx.AsyncClient
httpx.AsyncClient = Spy
try:
    for port in (9100, 502):
        assert asyncio.run(shelly_gen1.probe("10.0.0.5", port)) == {"online": False}
        assert asyncio.run(shelly_gen2.battery_probe("10.0.0.5", port)) == {}
    assert not opened, "a Shelly adapter opened a client for a no-talk port"
    asyncio.run(shelly_gen1.probe("10.0.0.5", 80))
    assert opened, "the normal port is still asked"
finally:
    httpx.AsyncClient = real_client

# 3) the routes: a body that is not a dictionary is a 400 (it was a 500), a bad or no-talk port is not saved
app = FastAPI()
app.include_router(device_routes.router)


async def no_settle(added):
    return None


device_routes._settle_added = no_settle
client = TestClient(app, raise_server_exceptions=False)
for body in ("[]", '"x"', "not json", "123", "null"):
    r = client.post("/api/devices/add", content=body, headers={"content-type": "application/json"})
    assert r.status_code == 400, (body, r.status_code, r.text[:100])
r = client.post("/api/devices/add", json={"devices": [{"ip": "10.0.0.9", "port": 9100}, {"ip": "10.0.0.10", "port": "abc"}, {"ip": "10.0.0.11", "port": "8080"}]})
assert r.status_code == 200, r.text[:200]
ports = {d["ip"]: d["port"] for d in r.json()["added"]}
assert ports == {"10.0.0.9": 80, "10.0.0.10": 80, "10.0.0.11": 8080}, "a no-talk or bad port is left out (the default stays), a good one is kept: %s" % ports
device_id = r.json()["added"][0]["id"]
for port in (9100, 502, 0, 70000):
    r = client.post(f"/api/devices/{device_id}/rename", json={"name": "Printer", "port": port})
    assert r.status_code == 400, (port, r.status_code)
print("TUTTO OK")
