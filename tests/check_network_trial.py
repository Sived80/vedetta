"""«Try and add» (POST /api/networks/test, networks/trial.py): a network behind the router is tried before it is added, and nothing is saved.
The candidate is checked as an add is (same codes, same 400s); every address of it is pinged once (the excluded ranges never), and the answer
says how many answered, a few of them, and what Vedetta would see of it function by function (the judge, as in the list). networks.json is not
written, the list is the same as before. The path «test» is not taken for a network called "test". Fake ping, fake host network, temporary data
folder, invented private addresses only.
    python tests/check_network_trial.py"""
import os
import sys
import tempfile
from pathlib import Path

DATA = tempfile.mkdtemp()
os.environ["VEDETTA_DATA_DIR"] = DATA
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.networks import registry  # noqa: E402
from app.routes import network_routes  # noqa: E402
from app.scan import latency  # noqa: E402
from app.storage import devices_config, network_store  # noqa: E402
from app.storage.history import history  # noqa: E402

registry.ROUTE_FILE = os.path.join(DATA, "no-route-file")   # the fake network, not the routes of this computer
ANSWER = {"192.168.60.5", "192.168.60.9", "192.168.60.40"}
asked: list = []


async def fake_main():
    return "192.168.50.0/24", "192.168.50.2"


async def fake_ping(ip, timeout):
    asked.append(ip)
    return 1.5 if ip in ANSWER else None


registry.main = fake_main
latency.icmp_ms = fake_ping
devices_config.load_devices = lambda: [{"id": "a", "ip": "192.168.50.9"}]
history.last_presence = lambda: {}
c = TestClient(FastAPI())
c.app.include_router(network_routes.router)
listed = c.get("/api/networks").json()

# 1) a /24 with a range left out: 254 addresses minus 10, three answer
body = {"id": "try1", "cidr": "192.168.60.0/24", "via": ["routed"], "state": "confirmed", "name": "IoT", "vlan": 60, "exclude": ["192.168.60.30-192.168.60.39"]}
r = c.post("/api/networks/test", json=body)
assert r.status_code == 200, r.text
got = r.json()
assert len(asked) == 244 and not [ip for ip in asked if ip.startswith("192.168.60.3") and len(ip) == 13], len(asked)
assert got["asked"] == 244 and got["answer"] == 3 and got["sample"] == ["192.168.60.5", "192.168.60.9", "192.168.60.40"], got
assert got["cidr"] == "192.168.60.0/24" and got["vlan"] == 60 and sorted(got["caps"]) == sorted(["pres", "name", "mac", "port", "deep", "quiet", "stray"]), got
assert got["caps"]["pres"] == {"state": "on", "source": "ved", "by": "ping"}, got["caps"]

# 2) nothing saved, the list is the same
assert not (Path(DATA) / "networks.json").exists() and network_store.rows() == []
assert c.get("/api/networks").json() == listed

# 3) refused as an add is: too wide, the main network, a public one; nobody pinged
asked.clear()
for bad, code in (("192.168.0.0/16", 400), ("192.168.50.0/24", 400), ("8.8.8.0/24", 400), ("nonsense", 400)):
    r = c.post("/api/networks/test", json={**body, "cidr": bad})
    assert r.status_code == code and r.json()["detail"]["code"].startswith("E_"), (bad, r.text)
assert asked == []
# a direct call that says "direct": a /16 would be valid for an add, but a try pings only as wide as a network behind the router may be (19/11 review)
r = c.post("/api/networks/test", json={**body, "cidr": "10.20.0.0/16", "via": ["direct"], "exclude": []})
assert r.status_code == 400 and r.json()["detail"]["code"] == "E_TOO_WIDE" and asked == [], r.text
for via in ([1, "routed"], [None, "routed"], [["routed"]]):          # a list of mixed things is a refusal, never a 500
    r = c.post("/api/networks/test", json={**body, "via": via})
    assert r.status_code == 400 and r.json()["detail"]["code"].startswith("E_") and asked == [], (via, r.text)

# 4) nobody answers: still an answer, with the judge; then the add works as before
ANSWER.clear()
got = c.post("/api/networks/test", json={**body, "cidr": "192.168.61.0/30", "exclude": []}).json()
assert got["asked"] == 2 and got["answer"] == 0 and got["sample"] == [], got
assert c.post("/api/networks", json=body).status_code == 200 and [r["id"] for r in network_store.rows()] == ["try1"]
r = c.post("/api/networks/test", json=body)
assert r.status_code == 400 and r.json()["detail"]["code"] in ("E_OVERLAP", "E_DUP_ID"), r.text
print("check_network_trial: ok")
