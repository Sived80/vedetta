"""Golden-master test of identity_shift.profile (what the app remembers about one MAC: DHCP card, Bonjour card, Home Assistant registry, vendor, memory per MAC) with the DHCP tables and
helpers, the Bonjour table, the Home Assistant lookup, the vendor lookup and the placeholder test replaced by in-memory fakes that record every call: 3000 generated MACs and memories
(None/empty/partial, live DHCP data that overrides the memory, placeholder and non-text names, empty or partial registry cards, falsy values) must give exactly the same profile (key ORDER
included, or the exception) AND the same ordered calls as the code before the function was split. tests/golden/identity_profile.json keeps one sha1 per case plus a readable sample.
Regenerate only on purpose:  IDENTITY_PROFILE_GOLDEN_UPDATE=1 python tests/check_identity_profile_golden.py"""
import hashlib
import json
import os
import random
import sys
import tempfile
import types
import zlib
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()      # never the real folder of the developer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import identity_shift  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "identity_profile.json"
N = 3000
rng = random.Random(9191)
LOG: list = []
CASE = [0]


def pick(seq):
    return seq[rng.randrange(len(seq))]


def h(*parts):
    return zlib.crc32(repr((CASE[0],) + parts).encode())


class LoggedDict(dict):
    def __init__(self, name, *a):
        super().__init__(*a)
        self.name = name

    def get(self, key, default=None):
        LOG.append([self.name + ".get", repr(key)])
        return super().get(key, default)


def fake_is_private(mac):
    LOG.append(["is_private_mac", repr(mac)])
    return [True, False, None, 0][h("priv", repr(mac)) % 4]


def fake_os_family(prl, cls):
    LOG.append(["_os_family", repr(prl), repr(cls)])
    return [None, "windows", "android", ""][h("fam", repr(prl), repr(cls)) % 4]


def fake_lookup(mac, ip):
    LOG.append(["ha.lookup", repr(mac), repr(ip)])
    return [None, {}, {"manufacturer": "Acme", "model": "M1", "name": "Lamp"}, {"model": "M2"}, {"area": "kitchen"}, {"name": None, "manufacturer": ""}][h("ha", repr(mac)) % 6]


def fake_vendor(mac):
    LOG.append(["lookup_vendor", repr(mac)])
    return [None, "", "Espressif", "Apple"][h("ven", repr(mac)) % 4]


def fake_placeholder(name):
    LOG.append(["is_placeholder", repr(name)])
    return name in ("android", "iphone") or h("ph", repr(name)) % 5 == 0


def setup():
    seen = LoggedDict("dhcp.seen")
    by_mac = LoggedDict("mdns.by_mac")
    for mac in ("aa:01", "aa:02", "", "bb:03"):
        if rng.random() < 0.5:
            seen[mac] = pick([{"vendor_class": "MSFT 5.0", "hostname": "PC-One", "prl": "1,3,6"}, {}, None, {"hostname": "android"}, {"vendor_class": "ps5", "hostname": ""},
                              {"hostname": 5}, {"vendor_class": "", "hostname": "IPhone", "prl": None}, {"hostname": "Laptop"}])
        if rng.random() < 0.5:
            by_mac[mac] = pick([{"name": "Salotto"}, {}, None, {"name": ""}, {"name": None}, {"name": "MacBook Pro"}])
    identity_shift.dhcp = types.SimpleNamespace(seen=seen, is_private_mac=fake_is_private, _os_family=fake_os_family)
    identity_shift.mdns_listener = types.SimpleNamespace(by_mac=by_mac)
    identity_shift.ha_registry = types.SimpleNamespace(lookup=fake_lookup)
    identity_shift.vendor_lookup = types.SimpleNamespace(lookup_vendor=fake_vendor)
    identity_shift.naming = types.SimpleNamespace(is_placeholder=fake_placeholder)


def make_mem():
    r = rng.random()
    if r < 0.15:
        return pick([None, {}])
    m = {}
    for key, opts in (("dhcp_class", [None, "", "MSFT 5.0", "dhcpcd-5"]), ("dhcp_name", [None, "", "Host-X", "android", "IPHONE", "Mem Name"]),
                      ("ip", [None, "", "10.0.0.5"]), ("grp", [None, "", "pc", "phone", "generic"]), ("first_seen", [None, 0, 12.5, 1700000000])):
        if rng.random() < 0.6:
            m[key] = pick(opts)
    return m


out = []
for i in range(N):
    CASE[0] = i
    setup()
    mac = pick(["aa:01", "aa:02", "", "bb:03", "cc:04", None])
    mem = make_mem()
    LOG.clear()
    try:
        res = identity_shift.profile(mac, mem)
    except Exception as exc:
        res = ["EXC", type(exc).__name__]
    out.append({"res": res, "keys": list(res) if isinstance(res, dict) else None, "log": list(LOG)})


def digest(x):
    return hashlib.sha1(json.dumps(x, default=str).encode()).hexdigest()[:20]      # key order matters: no sort_keys


mine = {"digests": [digest(o) for o in out], "sample": json.loads(json.dumps(out[:25], default=str))}
if os.environ.get("IDENTITY_PROFILE_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(mine, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want["digests"]) == len(mine["digests"]) == N
for i, (x, y) in enumerate(zip(mine["digests"], want["digests"])):
    assert x == y, "case %d differs: %s" % (i, json.dumps(out[i], default=str)[:800])
assert mine["sample"] == want["sample"]
ok = [o["res"] for o in out if o["keys"]]
assert len(ok) > 2400 and sum(1 for o in out if not o["keys"]) > 10
assert all(list(r) == ["mac", "ip", "private", "dhcp_class", "family", "dhcp_name", "grp", "mdns_name", "ha", "vendor", "first_seen"] for r in ok)
assert sum(1 for r in ok if r["dhcp_name"]) > 300 and sum(1 for r in ok if r["dhcp_name"] is None) > 300 and sum(1 for r in ok if r["mdns_name"]) > 200 and sum(1 for r in ok if r["mdns_name"] is None) > 300
assert sum(1 for r in ok if r["ha"]) > 300 and sum(1 for r in ok if r["ha"] is None) > 300 and any(r["ha"] == (None, None, None) for r in ok)
assert sum(1 for r in ok if r["first_seen"] == 0) > 300 and sum(1 for r in ok if r["first_seen"]) > 300 and sum(1 for r in ok if r["dhcp_class"]) > 300
assert sum(1 for r in ok if r["dhcp_class"] == "MSFT 5.0") > 100 and sum(1 for r in ok if r["dhcp_name"] == "host-x") > 20 and sum(1 for r in ok if r["dhcp_name"] == "pc-one") > 20
print("TUTTO OK")
