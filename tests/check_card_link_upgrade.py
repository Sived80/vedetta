"""The card -> MAC link across an update from an older devices.yaml and back (1.0 step P4): a file without seq, with fields this version does not
know and with a `mac` written by hand (a wrong one: it is never read), and a database with the history of the cases of the rule. The start goes as
in main.py (ensure_seq_safely, the database opened, one judgement of the links): exactly the right links, devices.yaml untouched but for seq. Then
what the older code does with the very functions of devices_config (which P4 does not change), not knowing the table: a card removed and its
address added again (same id, new seq), two cards of a phone merged, two addresses swapped. One more judgement: the removed card's row is gone, the
card added again inherits nothing, the swapped cards keep their links (a link follows the device, never the address)."""
import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import cardlink_cycle, maclayer, netutil  # noqa: E402
from app.scan import dhcp, mdns_listener  # noqa: E402
from app.storage import devices_config as dc  # noqa: E402
from app.storage.history import History  # noqa: E402
from app.networks import registry as _routes  # noqa: E402
_routes.ROUTE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "no-route-file")   # the fake network, not the routes of this computer

Obs = maclayer.Observation
DAY = 86400
LAMP, TV, PHONE, PHONE2, NEWCOMER, REP, CAM = ("02:00:00:00:70:01", "02:00:00:00:70:02", "06:00:00:00:70:03", "06:00:00:00:70:04",
                                               "02:00:00:00:70:05", "02:00:00:00:70:0A", "02:00:00:00:70:06")
tmp = Path(tempfile.mkdtemp())
dc.CONFIG_DIR = tmp
dc.DEVICES_PATH = tmp / "devices.yaml"
netutil.last_network = "10.0.70.0/24"
mdns_listener.by_mac.clear()
dhcp.seen.clear()

OLD = {"devices": [
    {"id": "lamp", "name": "Lamp", "ip": "10.0.70.11", "adapter": "generic", "mac": "aa:bb:cc:dd:ee:01", "future_field": {"a": [1, 2]}},
    {"id": "tv", "name": "TV", "ip": "10.0.70.12", "adapter": "generic", "type_source": "user", "type": "tv"},
    {"id": "phone", "name": "Phone", "ip": "10.0.70.13", "adapter": "ping"},                   # behind the repeater
    {"id": "phone-b", "name": "Phone b", "ip": "10.0.70.14", "adapter": "ping"},               # the second card of the same phone (old address)
    {"id": "rep", "name": "Repeater", "ip": "10.0.70.20", "adapter": "generic"},               # its MAC is lent
    {"id": "moved", "name": "Laptop", "ip": "10.0.70.15", "adapter": "generic"},               # the laptop left, a newcomer took the address
    {"id": "scan-10-0-70-16", "name": "Camera", "ip": "10.0.70.16", "adapter": "generic"},
]}
text = yaml.safe_dump(OLD, allow_unicode=True, sort_keys=False)
dc.DEVICES_PATH.write_text(text, encoding="utf-8")

H = History(tmp / "vedetta.db")
now = time.time()
for i in range(30):                               # the last half hour of ARP views
    t = now - 1800 + i * 60
    H.observe([Obs("10.0.70.11", LAMP, "arp", t), Obs("10.0.70.12", TV, "arp", t), Obs("10.0.70.15", NEWCOMER, "arp", t),
               Obs("10.0.70.16", CAM, "arp", t), Obs("10.0.70.13", REP if i % 3 else PHONE, "arp", t)]
              + [Obs(f"10.0.70.{20 + k}", REP, "arp", t) for k in range(3)])
H.record_presence("moved", "10.0.70.15", "02:00:00:00:70:99", True, now - 20 * DAY)      # the laptop, three weeks ago
H.record_presence("moved", "10.0.70.15", NEWCOMER, True, now - 6 * DAY)
H.record_presence("phone", "10.0.70.13", REP, True, now - 2 * DAY)                        # the repeater answered for the phone once
H.record_presence("phone", "10.0.70.13", PHONE, True, now - DAY)
H.record_presence("lamp", "10.0.70.11", LAMP, True, now - 30 * DAY)                       # steady for a month: no event since


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def judge(at):
    cardlink_cycle._last = 0.0
    run(cardlink_cycle.update(H, now=at))


def links():
    return {d: (r["seq"], r["mac"], r["state"], r["source"]) for d, r in H.card_links().items()}


# the start of the new version: numbers given, database opened, one cycle (the verdict, then the links: the seed)
assert dc.ensure_seq_safely() == 7
maclayer.after_verdict(cardlink_cycle.update)
cardlink_cycle._last = 0.0
run(maclayer.record({}, H))
seq = {d["id"]: d["seq"] for d in dc.load_devices()}
assert links() == {"lamp": (seq["lamp"], LAMP, "linked", "seed"), "tv": (seq["tv"], TV, "linked", "seed"), "phone": (seq["phone"], PHONE, "linked", "seed"),
                   "scan-10-0-70-16": (seq["scan-10-0-70-16"], CAM, "linked", "seed")}, links()
reasons = dict(cardlink_cycle._unlinked)
assert reasons == {"no_answer": 1, "shared_kind": 1, "history_mixed": 1}, reasons    # phone-b (nobody), the repeater, the laptop's card
after = yaml.safe_load(dc.DEVICES_PATH.read_text(encoding="utf-8"))
assert [{k: v for k, v in c.items() if k != "seq"} for c in after["devices"]] == OLD["devices"], "devices.yaml untouched but for seq"
assert after["devices"][0]["mac"] == "aa:bb:cc:dd:ee:01" and links()["lamp"][1] == LAMP, "the hand-written mac is never read"

# what the older code does, not knowing the table: a card removed and its address added again, a phone merged, two addresses swapped
dc.remove_device("scan-10-0-70-16")
added = dc.add_devices([{"ip": "10.0.70.16", "name": "Camera 2", "adapter": "generic"}])
assert added and added[0]["id"] == "scan-10-0-70-16" and added[0]["seq"] != seq["scan-10-0-70-16"], "same id, new seq"
H.reassign_device("phone-b", "phone")
dc.remove_device("phone-b")
ips = {d["id"]: d["ip"] for d in dc.load_devices()}
assert dc.set_ips({"lamp": (ips["lamp"], ips["tv"]), "tv": (ips["tv"], ips["lamp"])})
for i in range(10):                               # the lamp and the TV really swapped their addresses
    t = now + i * 60
    H.observe([Obs("10.0.70.12", LAMP, "arp", t), Obs("10.0.70.11", TV, "arp", t), Obs("10.0.70.16", CAM, "arp", t)])
run(maclayer.store_verdict(H, now=now + 600))

# the next judgement of the new code
judge(now + 600)
got = links()
assert "scan-10-0-70-16" not in got, "the camera added again does not inherit the old link (another seq): the row is deleted"
assert got["lamp"] == (seq["lamp"], LAMP, "linked", "seed") and got["tv"] == (seq["tv"], TV, "linked", "seed"), "the swapped cards keep their links"
assert got["phone"] == (seq["phone"], PHONE, "linked", "seed")
judge(now + 1200)
assert links()["scan-10-0-70-16"] == (added[0]["seq"], CAM, "linked", "rule"), "judged as a new card, by itself"
print("TUTTO OK")
