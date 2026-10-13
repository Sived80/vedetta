"""Topology, phase T0: the links «client is behind this repeater» that the data already prove. A MAC lent to several cards at the same time (storage/overlap.py)
marks a repeater, and every other card that used it is behind it. Real shapes (masked): one repeater lending its MAC to three phones for days, a phone that
moved to another address (not behind anything), a lent MAC nobody owns."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.topology import edges  # noqa: E402

H = 3600.0
NOW = 200 * H
REPEATER = "4e:3a:fd:00:00:01"

# the repeater is a card that answers with its own MAC; three phones were online with that MAC for hours, one for a day
events = [("rep", REPEATER, True, 1 * H), ("p1", REPEATER, True, 2 * H), ("p1", None, False, 5 * H), ("p2", REPEATER, True, 3 * H),
          ("p2", None, False, 30 * H), ("p3", REPEATER, True, 4 * H), ("p3", None, False, 4.5 * H)]
found = {(e.client, e.parent): e for e in edges.lent_mac_edges(events, {REPEATER: ["rep"]}, NOW)}
assert set(found) == {("p1", "rep"), ("p2", "rep"), ("p3", "rep")}, sorted(found)
assert all(e.source == "lent_mac" for e in found.values())
assert found[("p2", "rep")].seen_s == 27 * H and found[("p3", "rep")].seen_s == 0.5 * H, found

# the confidence grows with the time the link was observed, and a short sight stays low
assert edges.confidence(found[("p2", "rep")]) == "high" and edges.confidence(found[("p1", "rep")]) == "medium" and edges.confidence(found[("p3", "rep")]) == "low"

# a lent MAC that no card owns: the parent is the MAC itself, a repeater that is not a card yet
nobody = edges.lent_mac_edges(events, {}, NOW)
assert {e.parent for e in nobody} == {"mac:" + REPEATER} and {e.client for e in nobody} == {"rep", "p1", "p2", "p3"}

# a phone whose card shows the lent MAC at this moment is a candidate too, but the repeater was online with it far longer
both = {(e.client, e.parent) for e in edges.lent_mac_edges(events, {REPEATER: ["p2", "rep"]}, NOW)}
assert ("p2", "rep") in both and ("rep", "p2") not in both, both

# one phone on two cards one after the other: no link
moved = [("old", "9a:42:31:00:00:01", True, 1 * H), ("old", None, False, 10 * H), ("new", "9a:42:31:00:00:01", True, 10 * H - 300)]
assert edges.lent_mac_edges(moved, {"9a:42:31:00:00:01": ["old"]}, NOW) == []

# coverage: how many cards have a known place
cards = ["rep", "p1", "p2", "p3", "tv", "nas"]
assert edges.clients_placed(cards, list(found.values())) == 3 / 6
print("TUTTO OK")
