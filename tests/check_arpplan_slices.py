"""1.0 step P8: one way to walk the network. With the length of the periodic check (`cycle_s`) a network up to a /24 is asked one slice a cycle,
in turn (the slice that waited longest), plus the known devices; the slice is as small as 32 addresses (decision 1A) and grows so that the
whole network is covered within ROUND_S, whatever the cycle (decision 2A). Without `cycle_s` (the quick search, until step P9) nothing
changes: a /24 is asked whole. Wider networks keep their /24 blocks as before.
    python tests/check_arpplan_slices.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import arpplan  # noqa: E402

NET, OWN = "192.168.1.0/24", "192.168.1.5"

# 1. the constants of the decisions
assert (arpplan.MIN_SLICE, arpplan.ROUND_S) == (32, 300), (arpplan.MIN_SLICE, arpplan.ROUND_S)

# 2. the size of the slice for the length of the cycle: never smaller than 32 addresses, the whole /24 within 5 minutes
size = {c: arpplan.slice_prefix(NET, c) for c in (10, 30, 60, 120, 300, 600)}
assert size == {10: 27, 30: 27, 60: 26, 120: 25, 300: 24, 600: 24}, size
assert arpplan.slice_prefix("192.168.1.0/26", 30) == 27 and arpplan.slice_prefix("192.168.1.0/28", 30) == 28, "a small network: one slice, the network itself"

# 3. one slice a cycle, the one that waited longest (never asked first, in address order), and the known devices outside it
p = arpplan.plan(NET, OWN, ["192.168.1.9", "192.168.1.200", "10.9.9.9", "not an ip"], {}, cycle_s=30)
assert p["blocks"] == ["192.168.1.0/27"], p["blocks"]
assert p["targets"] == ["192.168.1.0/27", "192.168.1.200"], p["targets"]
assert p["network"] == NET and p["total"] == 8 and p["done"] == 0, p
# a slice asked for the first time is never a starting point: the first check asks a home network whole, so what turns up later in a slice
# not yet asked is a new device (S37: a stranger at .230 joined before the turn of its slice and was taken as known)
assert p["fresh"] == [], p
ts = {"192.168.1.%d/27" % (32 * i): 1000.0 + i for i in range(8)}
ts["192.168.1.96/27"] = 5.0
p = arpplan.plan(NET, OWN, [], ts, cycle_s=30)
assert p["blocks"] == ["192.168.1.96/27"] and p["done"] == 8 and p["fresh"] == [], p
# all slices asked in turn: 8 cycles cover the /24
asked, ts = [], {}
for cycle in range(8):
    p = arpplan.plan(NET, OWN, [], ts, cycle_s=30)
    asked += p["blocks"]
    ts[p["blocks"][0]] = float(cycle)
assert sorted(asked) == sorted("192.168.1.%d/27" % (32 * i) for i in range(8)), asked
# the whole first lap of the slices, and a new size of slice after a change of cycle, mark nothing as a starting point
assert all(arpplan.plan(NET, OWN, [], {}, cycle_s=c)["fresh"] == [] for c in (10, 30, 60, 120, 300))

# 4. with a long cycle the slice grows; with a 5-minute cycle the /24 is asked whole every time
assert arpplan.plan(NET, OWN, [], {}, cycle_s=120)["blocks"] == ["192.168.1.0/25"]
assert arpplan.plan(NET, OWN, [], {}, cycle_s=300)["blocks"] == [NET]

# 5. without cycle_s: as before (the quick search until P9)
assert arpplan.plan(NET, OWN, ["192.168.1.9"], {}) is None
# 6. a wider network keeps its /24 blocks, own block first, with or without cycle_s
wide = arpplan.plan("10.0.0.0/16", "10.0.5.20", ["10.0.9.4"], {}, cycle_s=30)
assert wide["blocks"] == ["10.0.5.0/24", "10.0.0.0/24"] and wide == arpplan.plan("10.0.0.0/16", "10.0.5.20", ["10.0.9.4"], {}), wide
# 7. unreadable or IPv6: as before
assert arpplan.plan("not a network", "10.0.0.1", [], {}, cycle_s=30) is None and arpplan.plan("fe80::/64", "fe80::1", [], {}, cycle_s=30) is None

print("check_arpplan_slices OK")
