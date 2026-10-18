"""The detectors of the second group (health/detectors.py): cyclic drops of one device (a restart that repeats) and many devices that drop together (a common cause: the switch, the access point, the power). The thresholds are the ones chosen from the real exports
(tools/replay_health.py). The evidence holds counts only. And the drops are derived from the presence events in one place (health/signals.py)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.health import detectors, matrix, signals  # noqa: E402

NOW = 1_000_000.0
MIN = 60.0
ROWS = {r["id"]: r for r in matrix.load()}
PERIODIC = ROWS["H05"]["params"]
TOGETHER = ROWS["H06"]["params"]


def sig(drops, devices=20):
    return {"now": NOW, "drops": drops, "devices": devices}


# --- drops from presence events: the first sight is not a drop, an offline after an offline is not another one, a back-and-forth gives one drop each time
events = [("a", True, 10.0), ("a", False, 20.0), ("a", False, 25.0), ("a", True, 30.0), ("a", False, 40.0), ("b", False, 5.0), ("b", True, 6.0)]
assert signals.drops_by_device(events) == {"a": [20.0, 40.0]}, signals.drops_by_device(events)

# --- cyclic drops: a device that drops every ~10 minutes, seven times
regular = [NOW - 3600 + i * 10 * MIN for i in range(7)]
found = detectors.periodic_dropout(sig({"cam": regular}), PERIODIC)
assert len(found) == 1 and found[0].subject == "cam" and found[0].data["drops"] == 7 and abs(found[0].data["period_s"] - 600) < 1 and found[0].data["cv"] == 0, found

# a device that drops at random (the usual phone, a Wi-Fi plug) is not cyclic
irregular = [NOW - 3600 + t * MIN for t in (0, 1, 2, 30, 31, 55)]
assert detectors.periodic_dropout(sig({"phone": irregular}), PERIODIC) == []
# too few drops, a period too short to be a restart, a period too long to call it a cycle, and drops older than the window
assert detectors.periodic_dropout(sig({"x": regular[:4]}), PERIODIC) == []
assert detectors.periodic_dropout(sig({"x": [NOW - 600 + i * 30 for i in range(7)]}), PERIODIC) == [], "a drop every 30 seconds is a bad link, not a restart"
assert detectors.periodic_dropout(sig({"x": [NOW - 86400 + i * 8 * 3600 for i in range(5)]}), PERIODIC) == [], "every 8 hours is beyond the largest period"
old = [NOW - 3 * 86400 + i * 10 * MIN for i in range(7)]
assert detectors.periodic_dropout(sig({"x": old}), PERIODIC) == [], "drops older than the window are not looked at"
# the signal is unreadable: nothing, no crash
assert detectors.periodic_dropout({"now": NOW, "drops": 5}, PERIODIC) == [] and detectors.periodic_dropout({}, PERIODIC) == []

# --- drops together: six of twenty devices within two minutes
together = {"d%d" % i: [NOW - 1800 + i * 10] for i in range(6)}
found = detectors.simultaneous_drop(sig(together, devices=20), TOGETHER)
assert len(found) == 1 and found[0].subject == "lan" and found[0].data == {"devices": 6, "of": 20}, found
# four is not enough, and neither is a crowd that is a small part of a big network
assert detectors.simultaneous_drop(sig({"d%d" % i: [NOW - 1800] for i in range(4)}, devices=20), TOGETHER) == []
assert detectors.simultaneous_drop(sig({"d%d" % i: [NOW - 1800] for i in range(6)}, devices=60), TOGETHER) == [], "6 of 60 is 10%: below the share"
# drops spread over the hour are not together; old ones are not looked at
spread = {"d%d" % i: [NOW - 3000 + i * 600] for i in range(6)}
assert detectors.simultaneous_drop(sig(spread), TOGETHER) == []
assert detectors.simultaneous_drop(sig({"d%d" % i: [NOW - 5 * 3600] for i in range(8)}), TOGETHER) == []
assert detectors.simultaneous_drop({"now": NOW}, TOGETHER) == [] and detectors.simultaneous_drop({"now": NOW, "drops": {"a": [NOW]}, "devices": 0}, TOGETHER) == []

# --- both rows are in the matrix, in shadow, with a checked source
for rid in ("H05", "H06"):
    assert ROWS[rid]["status"] == "shadow" and ROWS[rid]["family"] in detectors.FAMILIES

print("check_health_detectors OK")
