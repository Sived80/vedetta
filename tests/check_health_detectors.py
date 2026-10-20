"""The detectors of the second group (health/detectors.py): cyclic drops of one device (a restart that repeats) and many devices that drop together (a common cause: the switch, the access point, the power). The thresholds are the ones chosen from the real exports
(tools/replay_health.py). The evidence holds counts and device ids, never an address or a name. And the drops are derived from the presence events in one place (health/signals.py)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.health import detectors, matrix, signals  # noqa: E402

NOW = 1_000_000.0
MIN = 60.0
ROWS = {r["id"]: r for r in matrix.load()}
PERIODIC = ROWS["H05"]["params"]
TOGETHER = ROWS["H06"]["params"]
STEP = ROWS["H07"]["params"]


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
assert len(found) == 1 and found[0].subject == "lan" and found[0].data == {"devices": 6, "of": 20, "ids": ["d0", "d1", "d2", "d3", "d4", "d5"]}, found
# the ids are those of the biggest group of the hour, not of every device that dropped
mixed = dict(together, late=[NOW - 300], later=[NOW - 100])
assert detectors.simultaneous_drop(sig(mixed, devices=20), TOGETHER)[0].data["ids"] == ["d0", "d1", "d2", "d3", "d4", "d5"]
# four is not enough, and neither is a crowd that is a small part of a big network
assert detectors.simultaneous_drop(sig({"d%d" % i: [NOW - 1800] for i in range(4)}, devices=20), TOGETHER) == []
assert detectors.simultaneous_drop(sig({"d%d" % i: [NOW - 1800] for i in range(6)}, devices=60), TOGETHER) == [], "6 of 60 is 10%: below the share"
# drops spread over the hour are not together; old ones are not looked at
spread = {"d%d" % i: [NOW - 3000 + i * 600] for i in range(6)}
assert detectors.simultaneous_drop(sig(spread), TOGETHER) == []
assert detectors.simultaneous_drop(sig({"d%d" % i: [NOW - 5 * 3600] for i in range(8)}), TOGETHER) == []
assert detectors.simultaneous_drop({"now": NOW}, TOGETHER) == [] and detectors.simultaneous_drop({"now": NOW, "drops": {"a": [NOW]}, "devices": 0}, TOGETHER) == []

# --- a step of the latency of the gateway: the last 15 minutes against the 6 hours before them (median and spread), with a floor in milliseconds because a wired LAN answers in half a millisecond
def series(base_ms, last_ms, spread=0.05, minutes_last=15):
    """One sample a minute: 6 hours at base_ms (a little noise), then the last minutes at last_ms."""
    out = []
    for i in range(6 * 60):
        out.append((NOW - (6 * 60 + minutes_last - 1 - i) * MIN, base_ms + (spread if i % 2 else -spread)))
    for i in range(minutes_last):
        out.append((NOW - (minutes_last - 1 - i) * MIN, last_ms + (spread if i % 2 else -spread)))
    return out


def lat(samples):
    return {"now": NOW, "latency": {"gateway": samples}}


found = detectors.step_change(lat(series(0.5, 8.0)), STEP)
assert len(found) == 1 and found[0].subject == "gateway" and found[0].data == {"from_ms": 0.5, "to_ms": 8.0}, found
assert detectors.step_change(lat(series(0.5, 0.55)), STEP) == [], "a flat series says nothing"
assert detectors.step_change(lat(series(0.5, 1.5)), STEP) == [], "three times as much but only one millisecond more: a wired LAN does that, below the floor"
assert detectors.step_change(lat(series(20.0, 30.0, spread=4.0)), STEP) == [], "a noisy link that rises a little is inside its own spread"
assert len(detectors.step_change(lat(series(20.0, 90.0, spread=4.0)), STEP)) == 1, "a noisy link that jumps well beyond its spread is a step"
# one spike is not a step (the median of the last minutes does not move), and too few samples are not enough to say anything
spike = series(0.5, 0.5)
spike[-1] = (spike[-1][0], 40.0)
assert detectors.step_change(lat(spike), STEP) == []
assert detectors.step_change(lat(series(0.5, 8.0)[-30:]), STEP) == [], "without the six hours before there is no baseline"
assert detectors.step_change(lat(series(0.5, 8.0, minutes_last=3)), STEP) == [], "three samples are not a window"
assert detectors.step_change({"now": NOW, "latency": {"gateway": 5}}, STEP) == [] and detectors.step_change({"now": NOW}, STEP) == [] and detectors.step_change({}, STEP) == []
assert detectors.step_change({"now": NOW, "latency": {"gateway": [(NOW, None)] * 100}}, STEP) == [], "samples without a value are left out"

# --- both rows are in the matrix, in shadow, with a checked source
for rid in ("H05", "H06", "H07"):
    assert ROWS[rid]["status"] == "shadow" and ROWS[rid]["family"] in detectors.FAMILIES

print("check_health_detectors OK")
