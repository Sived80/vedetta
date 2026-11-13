"""1.0 step P9 (decisions 1A, 2A): inventory_view.listable, what the "Search devices" button shows. Pure; private placeholder addresses.
- the hosts of the pass first (seen now), then the devices the inventory lists (confirmed or asleep), once per MAC whatever its spelling;
- never a card: a MAC linked to a card, or an address of a card without a link (decision 2A of P7); a linked card's old address is free.
    python tests/check_inventory_listable.py"""
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import inventory_view  # noqa: E402

LINKS = {"c1": {"state": "linked", "mac": "aa:bb:cc:00:00:01"}, "c2": None}
inventory_view.linkview.row = lambda cid: LINKS.get(cid)
CARDS = [{"id": "c1", "ip": "10.0.0.1"}, {"id": "c2", "ip": "10.0.0.2"}]
FRESH = [{"ip": "10.0.0.5", "mac": "aa-bb-cc-00-00-05", "hostname": "pc"},
         {"ip": "10.0.0.2", "mac": "AA:BB:CC:00:00:22", "hostname": None},        # at the address of the unlinked card: the card's
         {"ip": "10.0.0.9", "mac": "AA:BB:CC:00:00:01", "hostname": None}]        # the linked card at another address: configured
LISTED = [{"ip": "10.0.0.7", "mac": "AA:BB:CC:00:00:07", "last_seen": 50.0},      # the TV asleep
          {"ip": "10.0.0.5", "mac": "AA:BB:CC:00:00:05", "last_seen": 40.0},      # heard by the pass too
          {"ip": "10.0.0.1", "mac": "AA:BB:CC:00:00:11", "last_seen": 30.0}]      # at the linked card's old address: not the card

rows = inventory_view.listable(FRESH, CARDS, 1000.0, LISTED)
assert [(r["ip"], r["last_seen"]) for r in rows] == [("10.0.0.5", 1000.0), ("10.0.0.7", 50.0), ("10.0.0.1", 30.0)], rows
assert rows[0]["hostname"] == "pc" and rows[1]["hostname"] is None, rows
assert inventory_view.listable([], [], 1.0, []) == [], "nothing known, nothing heard: an empty list"
inventory_view._listed = LISTED[:1]
assert [r["ip"] for r in inventory_view.listable([], [], 1.0)] == ["10.0.0.7"], "by default the last cycle's inventory"
print("check_inventory_listable: ok")
