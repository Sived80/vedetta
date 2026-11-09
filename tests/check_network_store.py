"""The networks written by the person (storage/network_store.py, networks.json) and what the registry does with them.
1) no file: no network, and the registry is the main network alone; 2) add: checked (overlap with the main one, duplicate id, public range,
a whole search behind a router) and stored as written; 3) change and remove; 4) a row that no longer fits next to the main network is left out
of the answer but kept in the file; an unreadable file is no network; 5) registry: a confirmed network reached directly with touch "full" may
be searched in depth, a confirmed network behind the router may not (only its presence), a proposed or paused one is in no scope; ARP only on
the direct ones.
Invented private addresses only (10.x and 192.168.50-99.x).
    python tests/check_network_store.py"""
import json
import os
import sys
import tempfile
from pathlib import Path

DATA = tempfile.mkdtemp()
os.environ["VEDETTA_DATA_DIR"] = DATA
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.networks import model, registry  # noqa: E402
from app.storage import network_store as store  # noqa: E402

registry.ROUTE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "no-route-file")   # the fake network, not the routes of this computer
MAIN = registry.main_network("192.168.50.0/24")


def rejected(candidate, code):
    try:
        store.add(candidate, MAIN)
    except model.Rejected as exc:
        assert exc.code == code, (candidate, exc.code, code)
        return
    raise AssertionError(("accepted", candidate))


# 1) no file
assert store.load(MAIN) == ()
assert registry.scope_of("192.168.50.0/24").networks == (MAIN,)

# 2) add
iot = store.add({"id": "iot", "cidr": "192.168.60.0/24", "via": ["routed"], "state": "confirmed"}, MAIN)
assert iot.touch == "presence" and iot.state == "confirmed"
lab = store.add({"id": "lab", "cidr": "10.20.0.0/24", "via": ["direct"], "touch": "full", "state": "confirmed"}, MAIN)
cam = store.add({"id": "cam", "cidr": "192.168.70.0/24", "via": ["routed"]}, MAIN)
assert cam.state == "proposed"
rejected({"id": "x", "cidr": "192.168.50.128/25", "via": ["routed"]}, "E_OVERLAP")       # inside the main network
rejected({"id": "iot", "cidr": "192.168.80.0/24", "via": ["routed"]}, "E_DUP_ID")
rejected({"id": "pub", "cidr": "8.8.8.0/24", "via": ["routed"]}, "E_PUBLIC")
rejected({"id": "far", "cidr": "192.168.90.0/24", "via": ["routed"], "touch": "full"}, "E_TOUCH_NEEDS_DIRECT")
rejected(["not", "a", "dict"], "E_SHAPE")
rows = json.loads(Path(DATA, "networks.json").read_text(encoding="utf-8"))["networks"]
assert [r["id"] for r in rows] == ["iot", "lab", "cam"], rows
assert rows[0] == {"id": "iot", "cidr": "192.168.60.0/24", "via": ["routed"], "state": "confirmed", "touch": "presence", "exclude": []}, rows[0]
assert [n.id for n in store.load(MAIN)] == ["iot", "lab", "cam"]

# 3) change and remove
assert store.change("cam", {"state": "confirmed", "cidr": "10.0.0.0/8"}, MAIN).state == "confirmed"        # the network itself is not changed this way
assert str(store.load(MAIN)[2].cidr) == "192.168.70.0/24"
try:
    store.change("cam", {"touch": "full"}, MAIN)
    raise AssertionError("a whole search behind a router")
except model.Rejected as exc:
    assert exc.code == "E_TOUCH_NEEDS_DIRECT"
assert store.change("nope", {"state": "paused"}, MAIN) is None
assert store.change("cam", {"state": "paused"}, MAIN).state == "paused"

# 4) the main network moves over a written one: left out of the answer, kept in the file
moved = registry.main_network("192.168.60.0/23")
assert [n.id for n in store.load(moved)] == ["lab", "cam"], store.load(moved)
assert len(json.loads(Path(DATA, "networks.json").read_text(encoding="utf-8"))["networks"]) == 3
assert store.remove("cam") and not store.remove("cam")

# 5) registry
scope = registry.scope_of("192.168.50.0/24")
assert [n.id for n in scope.networks] == ["main", "iot", "lab"]
ips = ["192.168.50.4", "192.168.60.9", "10.20.0.7", "192.168.70.3", "8.8.8.8"]
assert scope.allowed(ips) == ["192.168.50.4", "192.168.60.9", "10.20.0.7"]
assert scope.searchable(ips) == ["192.168.50.4", "10.20.0.7"], scope.searchable(ips)     # behind the router: never searched in depth
assert scope.arp_targets(ips) == ["192.168.50.4", "10.20.0.7"]
store.change("lab", {"state": "paused"}, MAIN)
assert registry.scope_of("192.168.50.0/24").searchable(ips) == ["192.168.50.4"]

Path(DATA, "networks.json").write_text("{not json", encoding="utf-8")
assert store.load(MAIN) == () and registry.scope_of("192.168.50.0/24").networks == (MAIN,)
print("check_network_store: ok")
