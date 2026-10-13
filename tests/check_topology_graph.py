"""Topology, phase T1 (read-only): the links of every source put together, one best link per (client, parent), the clients with two different parents flagged as a conflict (a link
under analysis), and the cards with no known place told as unknown (never drawn as certain). Sources: the MAC lent by a repeater (observed for a time) and the device a Home Assistant
device declares to be connected through (declared by the integration: high confidence by itself). Pure."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.topology import edges, graph  # noqa: E402

H = 3600.0
lent = [edges.Edge("p1", "rep", edges.SOURCE_LENT_MAC, 2 * H), edges.Edge("p2", "rep", edges.SOURCE_LENT_MAC, 30 * H)]
declared = [edges.Edge("zb1", "hub", edges.SOURCE_HA_VIA, 0.0), edges.Edge("p1", "rep", edges.SOURCE_HA_VIA, 0.0)]

# a declared link is high by itself; an observed one by its time
assert edges.confidence(declared[0]) == "high" and edges.confidence(lent[0]) == "medium" and edges.confidence(lent[1]) == "high"

g = graph.build(["rep", "hub", "p1", "p2", "zb1", "tv", "nas"], lent, declared)
# one link per (client, parent): the same link from two sources is kept once, with both sources and the strongest confidence
assert set(g.links) == {("p1", "rep"), ("p2", "rep"), ("zb1", "hub")}, g.links
assert g.links[("p1", "rep")].sources == ["lent_mac", "ha_via_device"] and g.links[("p1", "rep")].confidence == "high"
assert g.links[("p2", "rep")].sources == ["lent_mac"] and g.links[("p2", "rep")].confidence == "high"
# parents (rep, hub) are not unknown; the clients that have a place are not either; the others are unknown, in the order of the cards
assert g.unknown == ["tv", "nas"], g.unknown
assert g.conflicts == []
assert round(graph.coverage(g, ["rep", "hub", "p1", "p2", "zb1", "tv", "nas"]), 3) == round(5 / 7, 3)

# two different parents for one client at similar strength: a conflict, told once, both links kept
clash = graph.build(["a", "r1", "r2"], [edges.Edge("a", "r1", edges.SOURCE_LENT_MAC, 30 * H), edges.Edge("a", "r2", edges.SOURCE_LENT_MAC, 30 * H)])
assert clash.conflicts == [("a", ["r1", "r2"])] and len(clash.links) == 2
# when one is clearly stronger the weaker one is not a conflict
quiet = graph.build(["a", "r1", "r2"], [edges.Edge("a", "r1", edges.SOURCE_LENT_MAC, 30 * H), edges.Edge("a", "r2", edges.SOURCE_LENT_MAC, 0.5 * H)])
assert quiet.conflicts == [] and quiet.links[("a", "r1")].confidence == "high"
# nothing at all
empty = graph.build([], [], [])
assert empty.links == {} and empty.unknown == [] and empty.conflicts == [] and graph.coverage(empty, []) == 0.0
print("TUTTO OK")
