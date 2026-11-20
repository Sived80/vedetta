"""What the panel «Networks» says of the life of a network (networks/activity.py) and the VLAN of a network the host reaches itself (networks/host_read.vlan_for).
1) the cards a network holds and how many are on now, from the last presence the history recorded of each card; 2) «mute»: a confirmed network
where no card is on and the newest answer of its cards is older than 24 hours (a card never recorded says nothing; a network with no card, a
proposed or paused one is never mute); 3) the VLAN: the VLAN id of the host's interface whose IPv4 address is in the network, None otherwise.
Invented private addresses only (10.x and 192.168.50-99.x).
    python tests/check_networks_activity.py"""
import ipaddress
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()          # nothing is written, but the log must never go to the real data folder
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.networks import activity, host_read  # noqa: E402
from app.networks.model import Network  # noqa: E402

DAY = 24 * 3600
NOW = 1_800_000_000.0
IOT = Network("iot", ipaddress.ip_network("192.168.60.0/24"), frozenset({"routed"}), "presence", "confirmed", ((int(ipaddress.ip_address("192.168.60.200")),) * 2,))
CARDS = [("a", "192.168.60.4"), ("b", "192.168.60.5"), ("c", "192.168.60.200"), ("d", "192.168.50.9"), ("e", None), ("f", "not an address"), ("g", "192.168.60.6")]


def tally(last, network=IOT, cards=CARDS):
    return activity.tally(network, cards, last, NOW)


# 1) cards and how many are on: the excluded address, another network and a card with no address do not count
got = tally({"a": (True, NOW - 5 * DAY), "b": (False, NOW - 60), "c": (True, NOW), "d": (True, NOW)})
assert got == {"cards": 3, "on": 1, "mute": False}, got
assert tally({}) == {"cards": 3, "on": 0, "mute": False}, "nothing recorded: nothing to say, not mute"

# 2) mute
assert tally({"a": (False, NOW - DAY - 1), "b": (False, NOW - 3 * DAY)})["mute"] is True
assert tally({"a": (False, NOW - DAY + 60), "b": (False, NOW - 3 * DAY)})["mute"] is False, "one card answered less than 24 hours ago"
assert tally({"a": (True, NOW - 9 * DAY), "b": (False, NOW - 3 * DAY)})["mute"] is False, "a card on since days: the network answers"
assert tally({"a": (False, NOW - 2 * DAY)})["mute"] is True, "the cards never recorded say nothing"
for state in ("proposed", "paused"):
    other = Network(IOT.id, IOT.cidr, IOT.via, IOT.touch, state)
    assert tally({"a": (False, NOW - 2 * DAY)}, network=other)["mute"] is False, state
assert tally({"d": (False, NOW - 2 * DAY)}, cards=[("d", "192.168.50.9")]) == {"cards": 0, "on": 0, "mute": False}, "no card: never mute"
assert activity.QUIET_S == DAY

# 3) the VLAN of a network the host reaches itself
HOST = {"interfaces": [
    {"name": "lo", "kind": "loopback", "ipv4": [{"address": "127.0.0.1", "prefix": 8}]},
    {"name": "enp0s18", "kind": "other", "ipv4": [{"address": "192.168.50.2", "prefix": 24}]},
    {"name": "enp0s18.60", "kind": "vlan", "vlan": {"id": 60, "parent": "enp0s18"}, "ipv4": [{"address": "192.168.60.100", "prefix": 24}]},
    {"name": "enp0s18.70", "kind": "vlan", "vlan": {"id": 70, "parent": "enp0s18"}, "ipv4": []},
]}
assert host_read.vlan_for(ipaddress.ip_network("192.168.60.0/24"), HOST) == 60
assert host_read.vlan_for(ipaddress.ip_network("192.168.50.0/24"), HOST) is None, "the main interface is not a VLAN"
assert host_read.vlan_for(ipaddress.ip_network("192.168.70.0/24"), HOST) is None, "a VLAN with no address in the network"
assert host_read.vlan_for(ipaddress.ip_network("192.168.60.0/24"), {}) is None
assert host_read.vlan_for(ipaddress.ip_network("192.168.60.0/24"), {"interfaces": [{"name": "x", "vlan": {"id": 9}, "ipv4": [{"address": "bad"}]}]}) is None
print("check_networks_activity: ok")
