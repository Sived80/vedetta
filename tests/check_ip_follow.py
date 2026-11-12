"""The address follows the MAC (1.0 step P5, IdentityUpkeep.follow_links): the linked cards found at another address in this cycle move there at
the end of the cycle, all in ONE write of devices.yaml (devices_config.set_ips): a move to a free address, an exchange of two cards, a chain of
three, a card without a link that held the address takes the one left free; two cards towards one address, or an address off the line, on
another network or in a paused one: nobody moves. Every card that moves gets the notice of a changed address, its misses go to zero, and the
cycle is woken once. A card without a link never follows an address by itself (decision 3A: the old "follow the IP" is gone)."""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

import yaml

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import netutil  # noqa: E402
from app.networks import registry  # noqa: E402
from app.state import DeviceState  # noqa: E402
from app.storage import devices_config  # noqa: E402

tmp = Path(tempfile.mkdtemp())
devices_config.DEVICES_PATH = tmp / "devices.yaml"
netutil.last_network = "10.0.0.0/24"
CARDS = [{"id": "a", "ip": "10.0.0.5", "name": "10.0.0.5", "seq": 1}, {"id": "b", "ip": "10.0.0.6", "name": "Printer", "seq": 2},
         {"id": "c", "ip": "10.0.0.7", "seq": 3}, {"id": "d", "ip": "10.0.0.8", "seq": 4}]
assert not hasattr(DeviceState, "follow_ip_changes"), "the old rule is gone"


def world():
    devices_config.DEVICES_PATH.write_text(yaml.safe_dump({"devices": [dict(c) for c in CARDS]}), encoding="utf-8")
    s = DeviceState()
    s.alerts, s.triggers = [], []
    s.emit_alert = lambda msg, key, **p: s.alerts.append((key, p))
    s.trigger = lambda force=False, reason="": s.triggers.append(reason)
    s.devices = {c["id"]: {"id": c["id"], "online": False, "name": c.get("name")} for c in CARDS}
    for c in CARDS:
        s._misses[c["id"]] = 2
    return s


def ips():
    return {d["id"]: d["ip"] for d in devices_config.load_devices()}


writes = []
real_set = devices_config.set_ips
devices_config.set_ips = lambda changes: (writes.append(dict(changes)), real_set(changes))[1]

# a move to a free address: one write, one notice, misses forgotten, one wake-up; the name that was the address follows it
s = world()
asyncio.run(s.follow_links({"a": "10.0.0.50"}))
assert ips() == {"a": "10.0.0.50", "b": "10.0.0.6", "c": "10.0.0.7", "d": "10.0.0.8"}, ips()
assert devices_config.load_devices()[0]["name"] == "10.0.0.50"
assert s.alerts == [("alert.ip_changed", {"label": "10.0.0.5", "old": "10.0.0.5", "new": "10.0.0.50"})], s.alerts
assert s._misses["a"] == 0 and s.triggers == ["ip_changed"] and len(writes) == 1, (s._misses, s.triggers, writes)

# an exchange (the case of 4b3f9dc) and a chain of three: one write, a notice per card, ONE wake-up
writes.clear()
s = world()
asyncio.run(s.follow_links({"a": "10.0.0.6", "b": "10.0.0.5"}))
assert ips()["a"] == "10.0.0.6" and ips()["b"] == "10.0.0.5" and len(writes) == 1 and len(s.alerts) == 2 and s.triggers == ["ip_changed"]
writes.clear()
s = world()
asyncio.run(s.follow_links({"a": "10.0.0.6", "b": "10.0.0.7", "c": "10.0.0.5"}))
assert (ips()["a"], ips()["b"], ips()["c"]) == ("10.0.0.6", "10.0.0.7", "10.0.0.5") and len(writes) == 1 and len(s.alerts) == 3

# a card (linked or not) that holds the address and does not move takes the one left free
writes.clear()
s = world()
asyncio.run(s.follow_links({"a": "10.0.0.8"}))
assert ips()["a"] == "10.0.0.8" and ips()["d"] == "10.0.0.5" and len(writes) == 1 and len(s.alerts) == 2, (ips(), s.alerts)

# nobody moves: two cards towards one address; an address on no direct network (off the line); an address of a paused network
writes.clear()
for moves in ({"a": "10.0.0.60", "b": "10.0.0.60"}, {"a": "10.9.9.9"}):
    s = world()
    asyncio.run(s.follow_links(moves))
    assert ips() == {c["id"]: c["ip"] for c in CARDS} and not writes and not s.alerts and not s.triggers, (moves, ips(), s.alerts)
registry.may_add = lambda ip: ip != "10.0.0.70"
s = world()
asyncio.run(s.follow_links({"a": "10.0.0.70"}))
assert ips()["a"] == "10.0.0.5" and not writes
# nothing to follow: nothing read, nothing written
s = world()
asyncio.run(s.follow_links({}))
assert not writes and not s.alerts and not s.triggers

# the file changed meanwhile (a card added at the address, or the card moved by another step): the write refuses, nothing is told
s = world()
devices_config.set_ips = lambda changes: None
asyncio.run(s.follow_links({"a": "10.0.0.50"}))
assert not s.alerts and not s.triggers and s._misses["a"] == 2
print("TUTTO OK")
