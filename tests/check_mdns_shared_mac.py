"""A MAC lent by a repeater to the clients behind it identifies none of them: what is announced at one address must not end up on the card of
another. Found in a real export: a repeater was typed "phone" because a card of a neighbour address (a mobile service) was filed under the lent MAC."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import mdns_listener as ml  # noqa: E402

REAL_IS_LENT = ml._is_lent_mac       # the test below first replaces it by the table of the moment, then puts the real one back

ml.STORE_PATH = Path(tempfile.mkdtemp()) / "mdns_seen.json"
LENT, OWN = "3c:a6:2f:11:22:33", "42:4b:cd:00:00:01"
ARP = {"10.0.0.105": LENT, "10.0.0.108": LENT, "10.0.0.50": OWN}
ml._mac_for_ip = lambda ip: ARP.get(ip)
ml._is_lent_mac = lambda mac: list(ARP.values()).count(mac) > 1

# an announcement from an address behind the repeater stays with that address
ml.record("10.0.0.108", "_nearbypresence._tcp", "nearby-phone", '""')
assert LENT not in ml.by_mac and "10.0.0.108" in ml.by_ip, (ml.by_mac, ml.by_ip)
assert ml.lookup(LENT, "10.0.0.105") is None                                  # the repeater itself gets nothing
assert "_nearbypresence._tcp" in ml.lookup(LENT, "10.0.0.108")["services"]   # the client behind it keeps its own card

# the periodic upkeep does not tie the address card to the lent MAC either
ml._housekeeping()
assert LENT not in ml.by_mac and "10.0.0.108" in ml.by_ip

# a card stored under the lent MAC by an older version is not given to any address
ml.by_mac[LENT] = {"name": "old", "services": ["_nearbypresence._tcp"], "ip": "10.0.0.108", "seen": 1.0, "score": 1}
assert ml.lookup(LENT, "10.0.0.105") is None

# a MAC of one address works as before: kept by MAC, found by MAC
ml.record("10.0.0.50", "_companion-link._tcp", "iPhone-di-Caio", '""')
assert OWN in ml.by_mac and "10.0.0.50" not in ml.by_ip and ml.lookup(OWN)["name"] == "iPhone-di-Caio"
# --- the repeater lends its MAC to clients that are not always awake: the answer must not depend on who is in the ARP table at this moment
# (found again in the export of 12 October: the same repeater went from router to phone and back, as the phone behind it woke and slept)
import time  # noqa: E402
ml.by_ip.clear(); ml.by_mac.clear()
ARP.clear(); ARP.update({"10.0.0.105": LENT, "10.0.0.50": OWN})      # the clients behind the repeater are asleep: the MAC is at ONE address now
ml._at_several_addresses = lambda mac: list(ARP.values()).count(mac) > 1
ml._is_lent_mac = REAL_IS_LENT
CALLS = []
SEEN = {LENT: 5, OWN: 2}                                             # the MAC layer saw the lent MAC at 5 addresses, an ordinary one at 2 (one device that got a new lease)


def counts(since):
    CALLS.append(since)
    return dict(SEEN)


ml._lent_counts = counts
ml._lent_memory.update(ts=0.0, macs=frozenset())
assert ml._is_lent_mac(LENT) and not ml._is_lent_mac(OWN), "5 addresses make a MAC lent; 2 do not"
ml.record("10.0.0.108", "_nearbypresence._tcp", "nearby-phone", '""')
assert LENT not in ml.by_mac and "10.0.0.108" in ml.by_ip, "an announcement of an address behind the repeater was filed under the repeater"
assert ml.lookup(LENT, "10.0.0.105") is None, "the repeater got the phone's Bonjour card while the phone was asleep"
ml.by_mac[LENT] = {"name": "old", "services": ["_nearbypresence._tcp"], "ip": "10.0.0.108", "seen": 1.0, "score": 1}      # left by a version that did not know
assert ml.lookup(LENT, "10.0.0.105") is None
ml.record("10.0.0.50", "_companion-link._tcp", "iPhone-di-Caio", '""')
assert OWN in ml.by_mac and ml.lookup(OWN)["name"] == "iPhone-di-Caio", "a MAC seen at two addresses only is still a device of its own"
assert len(CALLS) == 1, ("the counts are read once in LENT_REFRESH_S", CALLS)
# after the refresh time the count is read again; if it cannot be read the last answer stands, and nothing breaks
ml._lent_memory["ts"] = time.time() - ml.LENT_REFRESH_S - 1
SEEN.update({LENT: 1})
assert not ml._is_lent_mac(LENT) and len(CALLS) == 2
ml._lent_memory["ts"] = time.time() - ml.LENT_REFRESH_S - 1
ml._lent_counts = lambda since: 1 / 0
SEEN.update({LENT: 9})
assert not ml._is_lent_mac(LENT), "an error reading the count must leave the last answer"
print("TUTTO OK")
