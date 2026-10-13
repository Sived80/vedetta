"""«Shared» must mean at the same time. A MAC lent by a repeater answers for several cards at once; a phone that moved to a new address (two cards, one
private MAC) was never online on both for long. Real shapes (masked): a repeater lending its MAC to 3 phones for days, and two cards of one phone one after the other."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.storage import overlap  # noqa: E402

H = 3600.0
NOW = 100 * H

# intervals and their overlap
assert overlap.overlap_seconds([(0, 10)], [(5, 20)]) == 5
assert overlap.overlap_seconds([(0, 10)], [(10, 20)]) == 0
assert overlap.overlap_seconds([(0, 4), (6, 10)], [(3, 7)]) == 2

# sessions: an online event opens, an offline one closes, an open one ends at the horizon; each belongs to the MAC that opened it
events = [("a", "m1", True, 1 * H), ("a", None, False, 3 * H), ("a", "m2", True, 5 * H), ("b", "m1", True, 2 * H)]
got = sorted(overlap.sessions(events, NOW))
assert got == [("a", "m1", 1 * H, 3 * H), ("a", "m2", 5 * H, NOW), ("b", "m1", 2 * H, NOW)], got

# a repeater: three cards online together for hours on one MAC -> shared
lent = [("p1", "4e:3a:fd:00:00:01", True, 1 * H), ("p2", "4e:3a:fd:00:00:01", True, 2 * H), ("p3", "4e:3a:fd:00:00:01", True, 3 * H)]
assert overlap.shared_macs(lent, NOW) == {"4e:3a:fd:00:00:01"}

# one phone on two cards, one after the other (a few minutes of tolerance between them) -> not shared
moved = [("old", "9a:42:31:00:00:01", True, 1 * H), ("old", None, False, 10 * H), ("new", "9a:42:31:00:00:01", True, 10 * H - 300)]
assert overlap.shared_macs(moved, NOW) == set()

# two cards that really overlap for a short time only (a lease handed over) stay below the tolerance
brief = [("old", "9a:42:31:00:00:02", True, 1 * H), ("old", None, False, 10 * H), ("new", "9a:42:31:00:00:02", True, 10 * H - 600)]
assert overlap.shared_macs(brief, NOW) == set()

# one card alone, or the same card twice, is never shared; rows without a MAC are ignored
assert overlap.shared_macs([("a", "x", True, 1 * H), ("a", "x", True, 2 * H), ("b", None, True, 1 * H)], NOW) == set()
print("TUTTO OK")
