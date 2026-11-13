"""1.0 step P7, step 3: the guard of new devices reads the inventory (decisions 1A, 2A, 3A of 13/11).
  - what the guard sees (inventory_view.seen_now): the ARP view of the cycle plus the devices the inventory confirms that did not answer now
    (a device that answers one cycle in three no longer blinks); never a candidate, never a MAC the verdict calls lent or virtual;
  - "configured by address" only for the cards without a link (a console that takes a linked laptop's address is new); a linked MAC is configured;
  - the list of new devices keeps the ones asleep, with when they were last seen; nothing changes without history (the golden of the guard).
    python tests/check_inventory_guard.py"""
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import inventory_view, linkview, macverdict, netutil  # noqa: E402
from app.storage import newdevices  # noqa: E402
from app.storage.history import History  # noqa: E402
from app.networks import registry as _routes  # noqa: E402
_routes.ROUTE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "no-route-file")   # the fake network, not the routes of this computer

NOW = time.time()
TV, CAM, LAPTOP, CONSOLE, EXT, OLD = ("AA:00:00:00:00:%02X" % i for i in range(1, 7))
H = History(Path(tempfile.mkdtemp()) / "v.db")
inventory_view.history = H
netutil.last_network = "10.0.0.0/24"
macverdict.refresh({EXT: "lender"})


def put(ip, mac, source, first, last):
    with H._lock:
        H._db.execute("INSERT INTO ip_mac (ip, mac, source, first_seen, last_seen, seen_count) VALUES (?, ?, ?, ?, ?, 1)", (ip, mac, source, NOW - first, NOW - last))
        H._db.commit()


put("10.0.0.5", TV, "arp", 5000, 120)          # confirmed, silent for 2 minutes: not in the ARP view of this cycle
put("10.0.0.6", CAM, "dhcp", 300, 200)         # a DHCP request alone: candidate
put("10.0.0.7", EXT, "arp", 900, 30)           # a repeater that lends its MAC
put("10.0.0.8", OLD, "arp", 9000, 3000)        # confirmed, silent for 50 minutes: asleep

# 1. what the guard sees
arp = {"10.0.0.20": {"mac": LAPTOP, "vendor": "V"}}
seen = inventory_view.seen_now(arp, NOW)
assert seen == {"10.0.0.20": {"mac": LAPTOP, "vendor": "V"}, "10.0.0.5": {"mac": TV, "vendor": None}}, seen
assert inventory_view.seen_now({}, NOW, history=History(Path(tempfile.mkdtemp()) / "e.db")) == {}, "no history: the ARP view of before"
arp2 = {"10.0.0.5": {"mac": CAM}}
assert inventory_view.seen_now(arp2, NOW)["10.0.0.5"] == {"mac": CAM}, "what ARP says now at an address wins"

# 2. asleep and last seen for the list (3A)
assert newdevices.asleep_macs() == {OLD}, newdevices.asleep_macs()
assert abs(newdevices.last_seen_of(OLD) - (NOW - 3000)) < 1 and newdevices.last_seen_of(TV) is not None

# 3. configured by address only without a link; a linked MAC is configured (2A)
configs = [{"id": "laptop", "ip": "10.0.0.20"}, {"id": "lamp", "ip": "10.0.0.30"}]
linkview.load({"laptop": {"device_id": "laptop", "seq": 1, "network": "main", "mac": LAPTOP, "state": "linked", "reason": None, "source": "rule",
                          "ip": "10.0.0.20", "since": NOW - 3600, "changed": NOW - 3600}})
assert inventory_view.unlinked_ips(configs) == {"10.0.0.30"}
assert inventory_view.linked_macs(configs) == {LAPTOP}
linkview.load({})
assert inventory_view.unlinked_ips(configs) == {"10.0.0.20", "10.0.0.30"} and inventory_view.linked_macs(configs) == set()
try:
    inventory_view.unlinked_ips([{}])
except KeyError:
    pass
else:
    raise AssertionError("a card without an address fails as before (the guard logs it)")

# 4. the list of the new devices keeps the asleep ones, with when they were last seen
NH = History(Path(tempfile.mkdtemp()) / "n.db")
NH.meta_set(newdevices.BASELINE_KEY, "1")
newdevices.evaluate({OLD: {"ip": "10.0.0.8", "hostname": None, "vendor": None}, TV: {"ip": "10.0.0.5", "hostname": None, "vendor": None}}, set(), set(), hist=NH)
newdevices.evaluate({TV: {"ip": "10.0.0.5", "hostname": None, "vendor": None}}, set(), set(), hist=NH)     # OLD did not answer now
listed = {d["mac"]: d for d in newdevices.list_new(NH)}
assert set(listed) == {OLD, TV}, "asleep stays in the list"
assert abs(listed[OLD]["last_seen"] - (NOW - 3000)) < 1, listed[OLD]

print("check_inventory_guard OK")
