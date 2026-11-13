"""1.0 step P7, step 2: the neighbour table of the system as a source of the MAC layer ("neigh"). Every entry in a state that holds a MAC,
stamped with when the system last CONFIRMED it (the "used a/b/c" of `ip neigh`: b seconds ago), never with the time it is read: a STALE
entry of a device gone for hours stays on a home network for ever, and must not look seen now. Without that number (iproute2 without -s)
only a REACHABLE entry counts, as just confirmed. The verdict and the links never read this source (they read the ARP answers and DHCP).
    python tests/check_inventory_neigh.py"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import macclassify, maclayer  # noqa: E402
from app.scan import arpplan  # noqa: E402
from app.storage.history import History  # noqa: E402

BUSYBOX = ("10.0.0.5 lladdr aa:00:00:00:00:01 ref 1 used 0/3/0 probes 1 REACHABLE\n"
           "10.0.0.6 lladdr aa:00:00:00:00:02 used 7200/7200/7200 probes 1 STALE\n"
           "10.0.0.7  FAILED\n")
IPROUTE = ("10.0.0.5 dev e0 lladdr aa:00:00:00:00:01 REACHABLE\n10.0.0.6 dev e0 lladdr aa:00:00:00:00:02 STALE\n"
           "10.0.0.8 dev e0 lladdr aa:00:00:00:00:03  ref 1 used 1/0/1probes 4 DELAY\n")

# 1. the entries, with how long ago each was confirmed when the table says it
got = arpplan.parse_neighbor_entries(BUSYBOX)
assert got == [{"ip": "10.0.0.5", "mac": "AA:00:00:00:00:01", "state": "REACHABLE", "confirmed_age": 3},
               {"ip": "10.0.0.6", "mac": "AA:00:00:00:00:02", "state": "STALE", "confirmed_age": 7200}], got
got = arpplan.parse_neighbor_entries(IPROUTE)
assert [(e["ip"], e["state"], e["confirmed_age"]) for e in got] == [("10.0.0.5", "REACHABLE", None), ("10.0.0.6", "STALE", None), ("10.0.0.8", "DELAY", 0)], got
assert arpplan.parse_neighbors(BUSYBOX) == [{"ip": "10.0.0.5", "mac": "AA:00:00:00:00:01", "vendor": None}], "the REACHABLE rows of before"

# 2. the observations: stamped with the confirmation; without the number only REACHABLE, as now
NOW = 1_800_000_000.0
obs = maclayer.from_neigh(arpplan.parse_neighbor_entries(BUSYBOX), NOW)
assert [(o.ip, o.mac, o.source, o.ts) for o in obs] == [("10.0.0.5", "AA:00:00:00:00:01", "neigh", NOW - 3), ("10.0.0.6", "AA:00:00:00:00:02", "neigh", NOW - 7200)], obs
obs = maclayer.from_neigh(arpplan.parse_neighbor_entries(IPROUTE), NOW)
assert [(o.ip, o.source, o.ts) for o in obs] == [("10.0.0.5", "neigh", NOW), ("10.0.0.8", "neigh", NOW)], obs
assert maclayer.from_neigh([], NOW) == []

# 3. record() stores them with the rest; the verdict never reads them
H = History(Path(tempfile.mkdtemp()) / "v.db")
asyncio.run(maclayer.record({}, H, neighbours=arpplan.parse_neighbor_entries(BUSYBOX)))
rows = {(r["ip"], r["source"]): r for r in H.rows(0)}
assert set(rows) == {("10.0.0.5", "neigh"), ("10.0.0.6", "neigh")}, set(rows)
assert rows[("10.0.0.6", "neigh")]["last_seen"] < rows[("10.0.0.5", "neigh")]["last_seen"] - 7000, "the old entry keeps its old time"
assert "neigh" not in macclassify.ANSWER_SOURCES, "the verdict and the links read the ARP answers, never the neighbour table"
asyncio.run(maclayer.record({}, H))           # the callers of before: no neighbours, nothing else changes

print("check_inventory_neigh OK")
