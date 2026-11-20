"""The networks written by the person (storage/network_store.py, networks.json) and what the registry does with them.
1) no file: no network, and the registry is the main network alone; 2) add: checked (overlap with the main one, duplicate id, public range,
a whole search behind a router) and stored as written; 3) change and remove; 4) a row that no longer fits next to the main network is left out
of the answer but kept in the file; an unreadable file is no network; 5) registry: a confirmed network reached directly with touch "full" may
be searched in depth; a confirmed network behind the router only with touch "ports" (its ports and its model, decision «B» of 14/11: the
steps that cannot cross the router are left out, touch_policy.routed_steps), never with touch "presence"; a proposed or paused one is in no
scope; ARP only on the direct ones.
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
assert store.change("iot", {"touch": "ports"}, MAIN).touch == "ports"
routed = registry.scope_of("192.168.50.0/24")
assert routed.searchable(ips) == ["192.168.50.4", "192.168.60.9"], routed.searchable(ips)     # behind the router with "ports": searched (B, 14/11)
assert [ip for ip in ips if routed.through_router(ip)] == ["192.168.60.9"], "only the searchable address behind the router is searched through it"
assert not routed.through_router("192.168.50.4") and not routed.through_router("nope")
store.change("iot", {"touch": "presence"}, MAIN)
assert registry.scope_of("192.168.50.0/24").searchable(ips) == ["192.168.50.4"]

# 6) name and VLAN: written, changed, cleared; the name of the main network kept apart from the rows (the main network is never a row)
FILE = Path(DATA, "networks.json")
assert store.main_name() is None
media = store.add({"id": "media", "cidr": "192.168.80.0/24", "via": ["routed"], "name": "Media", "vlan": 80}, MAIN)
assert media.name == "Media" and media.vlan == 80
assert json.loads(FILE.read_text(encoding="utf-8"))["networks"][-1] == {"id": "media", "cidr": "192.168.80.0/24", "via": ["routed"], "name": "Media", "vlan": 80,
                                                                         "touch": "presence", "state": "proposed", "exclude": []}
assert store.change("media", {"name": "TV", "vlan": None}, MAIN).name == "TV" and store.load(MAIN)[-1].vlan is None
for bad, why in (({"name": 5}, "E_BAD_NAME"), ({"vlan": 4095}, "E_BAD_VLAN")):
    try:
        store.change("media", bad, MAIN)
        raise AssertionError(bad)
    except model.Rejected as exc:
        assert exc.code == why, (bad, exc.code)
store.set_main_name("Casa")
assert store.main_name() == "Casa" and [n.name for n in store.load(MAIN)][-1] == "TV"
store.change("media", {"state": "confirmed"}, MAIN)                     # writing the rows keeps the name of the main network
store.add({"id": "lab2", "cidr": "10.30.0.0/24", "via": ["direct"]}, MAIN)
assert store.remove("lab2") and store.main_name() == "Casa"
try:
    store.set_main_name(" Casa")
    raise AssertionError("a name with a space in front")
except model.Rejected as exc:
    assert exc.code == "E_BAD_NAME"
store.set_main_name(None)
assert store.main_name() is None

# 7) a file of the version before (no name, no VLAN, no main section) is read as it is; a file of this version, read the way the version
# before reads it (its fields only, "networks" only), still gives the same networks: going back one version loses the names, nothing else
FILE.write_text(json.dumps({"networks": [{"id": "iot", "cidr": "192.168.60.0/24", "via": ["routed"], "touch": "ports", "state": "confirmed", "exclude": []}]}), encoding="utf-8")
assert [(n.id, n.touch, n.name, n.vlan) for n in store.load(MAIN)] == [("iot", "ports", None, None)] and store.main_name() is None
store.change("iot", {"name": "IoT", "vlan": 60}, MAIN)
store.set_main_name("Casa")
data = json.loads(FILE.read_text(encoding="utf-8"))
OLD_FIELDS = ("id", "cidr", "via", "touch", "state", "exclude")
old_view = [model.validate({k: r[k] for k in OLD_FIELDS if k in r}, [MAIN]) for r in data["networks"]]
assert [(n.id, str(n.cidr), n.touch, n.state) for n in old_view] == [("iot", "192.168.60.0/24", "ports", "confirmed")]
assert data["main"] == {"name": "Casa"} and isinstance(data["networks"], list)

FILE.write_text("{not json", encoding="utf-8")
assert store.load(MAIN) == () and registry.scope_of("192.168.50.0/24").networks == (MAIN,)
assert store.main_name() is None
print("check_network_store: ok")
