"""The networks API (routes/network_routes.py), for the panel «Networks»: list, add, change, remove.
The main network comes first and is never written; a network that does not fit gets a 400 with its code and the translated reason; a change
of the network itself (its cidr) is ignored; an unknown network is a 404; each network says how many cards it holds.
Fake host network, temporary data folder, invented private addresses only.
    python tests/check_network_routes.py"""
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.networks import registry  # noqa: E402
from app.routes import network_routes  # noqa: E402
from app.storage import devices_config  # noqa: E402


async def fake_main():
    return "192.168.50.0/24", "192.168.50.2"


registry.main = fake_main
devices_config.load_devices = lambda: [{"id": "a", "ip": "192.168.50.9"}, {"id": "b", "ip": "192.168.60.4"}, {"id": "c", "ip": "192.168.60.5"}]
app = FastAPI()
app.include_router(network_routes.router)
c = TestClient(app)

got = c.get("/api/networks").json()
assert got["main"] == {"id": "main", "cidr": "192.168.50.0/24", "via": ["direct"], "touch": "full", "state": "confirmed", "cards": 1, "fits": True}, got
assert got["networks"] == [] and got["left_out"] == []

r = c.post("/api/networks", json={"id": "iot", "cidr": "192.168.60.0/24", "via": ["routed"], "state": "confirmed"})
assert r.status_code == 200, r.text
assert r.json()["networks"] == [{"id": "iot", "cidr": "192.168.60.0/24", "via": ["routed"], "touch": "presence", "state": "confirmed", "cards": 2, "fits": True}]

r = c.post("/api/networks", json={"id": "x", "cidr": "192.168.50.0/25", "via": ["routed"]}, headers={"Accept-Language": "de"})
assert r.status_code == 400 and r.json()["detail"]["code"] == "E_OVERLAP", r.text
assert r.json()["detail"]["message"] and r.json()["detail"]["message"] != "networks.error.E_OVERLAP", r.text
assert c.post("/api/networks", json=["no"]).status_code == 400

r = c.post("/api/networks/iot", json={"state": "paused", "cidr": "10.0.0.0/8"})
assert r.status_code == 200 and r.json()["networks"][0]["state"] == "paused" and r.json()["networks"][0]["cidr"] == "192.168.60.0/24", r.text
assert c.post("/api/networks/iot", json={"touch": "full"}).json()["detail"]["code"] == "E_TOUCH_NEEDS_DIRECT"
assert c.post("/api/networks/nope", json={"state": "paused"}).status_code == 404
assert c.delete("/api/networks/iot").json()["networks"] == []
assert c.delete("/api/networks/iot").status_code == 404
print("check_network_routes: ok")
