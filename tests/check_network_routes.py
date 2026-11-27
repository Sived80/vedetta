# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The networks API (routes/network_routes.py), for the panel «Networks»: list, add, change, remove.
The main network comes first and is never written; a network that does not fit gets a 400 with its code and the translated reason; a change
of the network itself (its cidr) is ignored; an unknown network is a 404; each network says how many cards it holds.
The fields added for the panel v10 (name, vlan, on, mute, caps) come on top: with them taken away every answer is exactly the one of the
version before (the same dictionaries as before, written out below). The main network gets a default name, translated, that the person can
change (POST /api/networks/main with a name: nothing else of it changes); the written ones a name and a VLAN number of their own.
Fake host network, fake presence history, temporary data folder, invented private addresses only.
    python tests/check_network_routes.py"""
import os
import sys
import tempfile
import time

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.networks import registry  # noqa: E402
from app.routes import network_routes  # noqa: E402
from app.storage import devices_config  # noqa: E402
from app.storage.history import history  # noqa: E402

registry.ROUTE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "no-route-file")   # the fake network, not the routes of this computer
NEW = ("name", "vlan", "on", "mute", "caps")
NOW = time.time()


async def fake_main():
    return "192.168.50.0/24", "192.168.50.2"


def before(row: dict) -> dict:
    """A row as the version before gave it: the new fields taken away, nothing else."""
    assert all(k in row for k in NEW), row
    return {k: v for k, v in row.items() if k not in NEW}


registry.main = fake_main
devices_config.load_devices = lambda: [{"id": "a", "ip": "192.168.50.9"}, {"id": "b", "ip": "192.168.60.4", "name_source": "nmap"}, {"id": "c", "ip": "192.168.60.5"}]
history.last_presence = lambda: {"a": (True, NOW - 60), "b": (False, NOW - 3 * 86400), "c": (False, NOW - 2 * 86400)}
app = FastAPI()
app.include_router(network_routes.router)
c = TestClient(app)

got = c.get("/api/networks").json()
assert before(got["main"]) == {"id": "main", "cidr": "192.168.50.0/24", "via": ["direct"], "touch": "full", "state": "confirmed", "cards": 1, "fits": True}, got
assert got["networks"] == [] and got["left_out"] == []
main = got["main"]
assert main["name"] == "Home" and main["vlan"] is None and main["on"] == 1 and main["mute"] is False, main
assert main["caps"]["pres"] == {"state": "on", "source": "ved", "by": "arp"} and "switch" not in main["caps"]["port"], main["caps"]
assert c.get("/api/networks", headers={"Accept-Language": "it"}).json()["main"]["name"] == "Casa"

r = c.post("/api/networks", json={"id": "iot", "cidr": "192.168.60.0/24", "via": ["routed"], "state": "confirmed"})
assert r.status_code == 200, r.text
assert [before(n) for n in r.json()["networks"]] == [{"id": "iot", "cidr": "192.168.60.0/24", "via": ["routed"], "touch": "presence", "state": "confirmed", "cards": 2, "fits": True}]
iot = r.json()["networks"][0]
assert iot["name"] is None and iot["vlan"] is None and iot["on"] == 0 and iot["mute"] is True, iot
assert iot["caps"]["pres"] == {"state": "on", "source": "ved", "by": "ping"} and iot["caps"]["name"] == {"state": "on", "source": "router", "by": "router_dns"}, iot["caps"]
assert iot["caps"]["port"]["state"] == "off" and iot["caps"]["port"]["switch"] == {"on": False, "touch_on": "ports", "touch_off": "presence"}
assert iot["caps"]["mac"]["state"] == "how" and iot["caps"]["stray"] == {"state": "soon"} and iot["caps"]["mac"]["ways"][2]["id"] == "ha_inside"        # 20/11: strays coming behind the router

r = c.post("/api/networks", json={"id": "x", "cidr": "192.168.50.0/25", "via": ["routed"]}, headers={"Accept-Language": "de"})
assert r.status_code == 400 and r.json()["detail"]["code"] == "E_OVERLAP", r.text
assert r.json()["detail"]["message"] and r.json()["detail"]["message"] != "networks.error.E_OVERLAP", r.text
assert c.post("/api/networks", json=["no"]).status_code == 400
r = c.post("/api/networks", json={"id": "y", "cidr": "192.168.70.0/24", "via": ["routed"], "vlan": 9999}, headers={"Accept-Language": "it"})
assert r.status_code == 400 and r.json()["detail"]["code"] == "E_BAD_VLAN" and "4094" in r.json()["detail"]["message"], r.text

# the two switches: touch is all it takes
r = c.post("/api/networks/iot", json={"touch": "ports", "name": "IoT", "vlan": 60})
iot = r.json()["networks"][0]
assert iot["name"] == "IoT" and iot["vlan"] == 60 and iot["caps"]["port"]["switch"]["on"] is True, iot
assert iot["caps"]["port"]["state"] == "how" and iot["caps"]["port"]["ways"][0]["params"] == {"from": "192.168.50.2", "to": "192.168.60.0/24"}, "asked, nobody answers: the firewall"
assert iot["caps"]["deep"] == iot["caps"]["port"], "behind the router the model follows the ports (B, 14/11)"
assert c.post("/api/networks/iot", json={"touch": "presence"}).json()["networks"][0]["caps"]["port"]["state"] == "off"

r = c.post("/api/networks/iot", json={"state": "paused", "cidr": "10.0.0.0/8"})
assert r.status_code == 200 and r.json()["networks"][0]["state"] == "paused" and r.json()["networks"][0]["cidr"] == "192.168.60.0/24", r.text
assert r.json()["networks"][0]["mute"] is False, "a paused network is not mute"
assert c.post("/api/networks/iot", json={"touch": "full"}).json()["detail"]["code"] == "E_TOUCH_NEEDS_DIRECT"
assert c.post("/api/networks/nope", json={"state": "paused"}).status_code == 404

# the name of the main network: the only thing of it the person writes
r = c.post("/api/networks/main", json={"name": "Casa mia", "touch": "presence", "cidr": "10.0.0.0/8"})
assert r.status_code == 200 and r.json()["main"]["name"] == "Casa mia", r.text
assert before(r.json()["main"]) == before(main), "nothing else of the main network changes"
assert c.post("/api/networks/main", json={"name": 7}).json()["detail"]["code"] == "E_BAD_NAME"
assert c.post("/api/networks/main", json={"name": None}).json()["main"]["name"] == "Home"
assert c.delete("/api/networks/main").status_code == 404

assert c.delete("/api/networks/iot").json()["networks"] == []
assert c.delete("/api/networks/iot").status_code == 404
print("check_network_routes: ok")
