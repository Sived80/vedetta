"""1.0 step P10, through the one writer on a database: a card linked to a private MAC (a phone); the phone rotates its MAC and takes another
address; DHCP says the same client identifier. At the next judgement the link passes to the new MAC (source "identity") and the export counts
it. Without the client identifier (another device), the link stays where it was.
    python tests/check_cardlink_succession_cycle.py"""
import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

import yaml

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import cardlink_cycle, maclayer, netutil  # noqa: E402
from app.scan import dhcp  # noqa: E402
from app.storage import devices_config  # noqa: E402
from app.storage.history import History  # noqa: E402
from app.networks import registry as _routes  # noqa: E402
_routes.ROUTE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "no-route-file")   # the fake network, not the routes of this computer

OLD, NEW = "DA:00:00:00:90:01", "DA:00:00:00:90:02"
IP, NEW_IP = "10.0.90.20", "10.0.90.31"
Obs = maclayer.Observation


def run(dhcp_new: dict) -> dict:
    tmp = Path(tempfile.mkdtemp())
    devices_config.DEVICES_PATH = tmp / "devices.yaml"
    netutil.last_network = "10.0.90.0/24"
    devices_config.DEVICES_PATH.write_text(yaml.safe_dump({"devices": [{"id": "phone", "ip": IP, "seq": 1, "name": "Telefono di Anna",
                                                                         "name_source": "user"}]}), encoding="utf-8")
    h = History(tmp / "v.db")
    now = time.time()
    for i in range(60):                                       # the phone answered for an hour with its old MAC ...
        h.observe([Obs(IP, OLD, "arp", now - 7200 + i * 60)])
    for i in range(55):                                       # ... then, two minutes after, with a new private MAC at another address
        h.observe([Obs(NEW_IP, NEW, "arp", now - 3480 + i * 60)])
    for i in range(4):                                        # other devices of the network
        h.observe([Obs("10.0.90.%d" % (100 + i), "3C:00:00:00:90:%02X" % i, "arp", now - 600)])
    h.store_card_links([{"device_id": "phone", "seq": 1, "network": "main", "mac": OLD, "state": "linked", "reason": None, "source": "rule",
                         "ip": IP, "since": now - 7200, "changed": now - 7200}], [], True)
    dhcp.seen.clear()
    dhcp.seen.update({OLD.lower(): {"hostname": "anna-phone", "client_id": "01:aa:90"}, NEW.lower(): dhcp_new})
    dhcp.seen.update({"3c:00:00:00:90:%02x" % i: {"hostname": "dev-%d" % i} for i in range(4)})
    asyncio.new_event_loop().run_until_complete(maclayer.store_verdict(h, now=now))
    cardlink_cycle._last = 0.0
    asyncio.new_event_loop().run_until_complete(cardlink_cycle.update(h, now=now))
    return {"link": h.card_links()["phone"], "counts": cardlink_cycle.counts(h)}


moved_before = cardlink_cycle._succession["moved"]
got = run({"hostname": "anna-phone", "client_id": "01:aa:90"})
assert (got["link"]["mac"], got["link"]["source"], got["link"]["state"]) == (NEW, "identity", "linked"), got["link"]
assert got["counts"]["successions"] == {"seen": 1, "moved": moved_before + 1} and got["counts"]["source"] == {"identity": 1}, got["counts"]

got = run({"hostname": "luca-phone", "client_id": "01:bb:90"})
assert got["link"]["mac"] == OLD and got["link"]["source"] == "rule", got["link"]
assert got["counts"]["successions"]["seen"] == 0

print("check_cardlink_succession_cycle OK")
