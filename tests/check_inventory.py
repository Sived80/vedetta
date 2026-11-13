"""1.0 step P7: the single inventory (inventory.build, pure). For every (network, MAC) seen in the last 7 days: the last address, the sources,
first and last sight, and the state (decision 1A of 13/11): candidate (one source, never an ARP answer), confirmed (an ARP answer, or two
different sources within 10 minutes), asleep (confirmed, not seen for more than 15 minutes), out after 7 days.
    python tests/check_inventory.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import inventory  # noqa: E402

NOW = 1_800_000_000.0
TV, CAM, PHONE, OLD, PAIR = "AA:00:00:00:00:01", "AA:00:00:00:00:02", "AA:00:00:00:00:03", "AA:00:00:00:00:04", "AA:00:00:00:00:05"


def row(ip, mac, source, first, last):
    return {"ip": ip, "mac": mac, "source": source, "first_seen": NOW - first, "last_seen": NOW - last}


rows = [
    row("10.0.0.5", TV, "arp", 3000, 60), row("10.0.0.5", TV, "dhcp", 3000, 2000),
    row("10.0.0.6", CAM, "dhcp", 500, 400),                                          # DHCP alone: candidate
    row("10.0.0.7", PHONE, "mdns", 900, 100), row("10.0.0.7", PHONE, "dhcp", 800, 300),   # two sources 200 s apart: confirmed
    row("10.0.0.8", OLD, "arp", 9 * 86400, 8 * 86400),                               # out after 7 days
    row("10.0.0.9", PAIR, "mdns", 9000, 8000), row("10.0.0.9", PAIR, "dhcp", 9000, 4000),  # two sources, but 4000 s apart: candidate, asleep never
    row("10.0.0.10", TV.replace("01", "0A"), "arp_dup", 100, 50),                    # the second MAC of a double answer: not an ARP answer of its own
    row("10.0.0.11", "aa:00:00:00:00:0b", "arp", 2000, 1000),                       # confirmed and silent for 1000 s: asleep
]
inv = inventory.build(rows, NOW)
state = {mac: e["state"] for (net, mac), e in inv.items()}
assert state == {TV: "confirmed", CAM: "candidate", PHONE: "confirmed", PAIR: "candidate", "AA:00:00:00:00:0A": "candidate",
                 "AA:00:00:00:00:0B": "asleep"}, state
tv = inv[("main", TV)]
assert tv["ip"] == "10.0.0.5" and tv["sources"] == {"arp", "dhcp"} and tv["first_seen"] == NOW - 3000 and tv["last_seen"] == NOW - 60, tv
assert inv[("main", PHONE)]["ip"] == "10.0.0.7" and inv[("main", PHONE)]["sources"] == {"mdns", "dhcp"}

# the last address wins when a MAC moved
moved = inventory.build([row("10.0.0.5", TV, "arp", 3000, 900), row("10.0.0.40", TV, "arp", 800, 30)], NOW)
assert moved[("main", TV)]["ip"] == "10.0.0.40", moved

# the network of each address (registry.direct_networks): the key is (network, MAC); an address of no direct network is left out
nets = {"10.0.0.5": "main", "10.0.20.5": "vlan20"}
two = inventory.build([row("10.0.0.5", TV, "arp", 100, 50), row("10.0.20.5", TV, "arp", 100, 40), row("192.168.9.9", CAM, "arp", 100, 40)], NOW,
                      network_of=nets.get)
assert set(two) == {("main", TV), ("vlan20", TV)}, set(two)

# a MAC in any case or with dashes is one MAC; a row without a usable MAC is left out
mixed = inventory.build([row("10.0.0.5", "aa-00-00-00-00-01", "arp", 100, 50), row("10.0.0.5", TV, "dhcp", 100, 40), row("10.0.0.6", "", "arp", 1, 1)], NOW)
assert list(mixed) == [("main", TV)] and mixed[("main", TV)]["sources"] == {"arp", "dhcp"}, mixed

# the constants of the decision
assert (inventory.CONFIRM_WINDOW_S, inventory.ASLEEP_S, inventory.KEEP_S) == (600, 900, 7 * 86400)

# the counts of the export: by state and by set of sources, numbers only
c = inventory.counts(inv)
assert c["states"] == {"confirmed": 2, "candidate": 3, "asleep": 1} and c["sources"]["arp+dhcp"] == 1 and c["macs"] == 6, c

print("check_inventory OK")
