"""The rule of the IP conflict as it ships (health/matrix.json) on a conflict where one of the two devices does not answer every ARP scan: a real network (01/11 export) had a camera always there and a
Shelly UNI on the same address that went quiet for 3 or 4 judgments in a row, 13 times in four days; with clear_cycles 3 the finding closed and opened again each time. The finding must stay open
across those gaps, close when the second device is gone for good, and the rule is shown (not in shadow). Pure: the signals are handed in, every address and MAC is made up."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.health import engine, matrix  # noqa: E402

H20 = next(r for r in matrix.load() if r["id"] == "H20")
STEP_S = 120                                   # one judgment every two minutes (ha/health_view.py REFRESH_S)
CONFLICT = {"conflicts": {"192.168.1.52": ["aa:bb:cc:00:00:01", "aa:bb:cc:00:00:02"]}}
QUIET = {"conflicts": {}}
GAPS = [3, 4, 3, 3, 4, 3, 4, 3, 3, 4, 3, 3, 4]   # the quiet judgments in a row seen on the real network, longest 4

assert H20["status"] == "active", "the IP conflict is shown to everyone: %s" % H20["status"]
assert H20["params"]["clear_cycles"] > 2 * max(GAPS), "the gaps of a device that answers now and then must not close the finding: %s" % H20["params"]

# --- the conflict goes on with gaps: opened and raised once, never closed
e = engine.Engine([H20])
changes, now = [], 0
for gap in GAPS:
    for _ in range(5):
        changes += e.judge(CONFLICT, now)
        now += STEP_S
    for _ in range(gap):
        changes += e.judge(QUIET, now)
        now += STEP_S
changes += e.judge(CONFLICT, now)
assert [c.change for c in changes] == ["opened", "raised"], [c.change for c in changes]
finding = e.findings()[0]
assert finding.state == "active" and finding.shadow is False and finding.first_seen == 0, finding

# --- the second device is gone (a fixed address given to it): the finding closes after clear_cycles quiet judgments, not before
quiet = []
for n in range(1, H20["params"]["clear_cycles"] + 1):
    now += STEP_S
    quiet.append((n, [c.change for c in e.judge(QUIET, now)]))
assert all(not ch for n, ch in quiet[:-1]) and quiet[-1][1] == ["closed"] and e.findings() == [], quiet
assert H20["params"]["clear_cycles"] * STEP_S <= 30 * 60, "a conflict that is solved leaves the page within half an hour"

print("check_health_h20_intermittent: ok")
