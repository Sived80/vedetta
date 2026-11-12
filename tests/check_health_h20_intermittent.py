"""The rule of the IP conflict as it ships (health/matrix.json) on a conflict where one of the two devices does not answer every ARP scan: a real network (01/11 export) had a camera always there and a
Shelly UNI on the same address that went quiet for 3 or 4 judgments in a row, 13 times in four days; when the rule read the last ARP scan alone the finding closed and opened again each time (and
clear_cycles 10 was put in to hold it). Since 1.0 step P3 the rule reads the single verdict: the whole chain runs here - observations of the ARP view in the store, the verdict of every cycle
(macclassify, its last evidence), macverdict, the signals of ha/health_view.py, the judge. The finding must open and be raised once, stay open across those gaps with clear_cycles 3, and close
within half an hour when the second device is gone for good. Every address and MAC is made up."""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import maclayer, macverdict  # noqa: E402
from app.ha import health_view  # noqa: E402
from app.health import engine, matrix  # noqa: E402
from app.storage.history import History  # noqa: E402

H20 = next(r for r in matrix.load() if r["id"] == "H20")
STEP_S = 120                                   # one cycle and one judgment every two minutes (ha/health_view.py REFRESH_S)
IP, CAM, RELAY = "10.0.52.52", "02:00:00:00:52:01", "02:00:00:00:52:02"
GAPS = [3, 4, 3, 3, 4, 3, 4, 3, 3, 4, 3, 3, 4]   # the quiet judgments in a row seen on the real network, longest 4

assert H20["status"] == "active", "the IP conflict is shown to everyone: %s" % H20["status"]
assert H20["params"] == {"min_cycles": 2, "clear_cycles": 3}, "the signal no longer blinks: the patch clear_cycles 10 is gone (%s)" % H20["params"]

h = History(Path(tempfile.mkdtemp()) / "vedetta.db")
e = engine.Engine([H20])
macverdict.refresh_conflicts([])
now = 1_800_000_000.0


def cycle(mac):
    """One cycle of the app (that MAC answers the view) and one judgment of the signals as health_view reads them."""
    global now
    h.observe(maclayer.from_arp({IP: {"mac": mac}}, now))
    asyncio.new_event_loop().run_until_complete(maclayer.store_verdict(h, now=now))
    signals = health_view.read_signals(now, presence=lambda since: [], latency=lambda now: {}, cards=lambda: [])
    changes = [c.change for c in e.judge(signals, now)]
    now += STEP_S
    return changes


# --- the conflict goes on with gaps: opened and raised once, never closed
changes = []
for gap in GAPS:
    for i in range(5):
        changes += cycle(RELAY if i % 2 == 0 else CAM)
    for _ in range(gap):
        changes += cycle(CAM)
changes += cycle(RELAY)
assert changes == ["opened", "raised"], changes
finding = e.findings()[0]
assert finding.state == "active" and finding.shadow is False, finding
assert finding.evidence == {"ips": 1, "macs": 2}, finding.evidence

# --- the second device is gone (a fixed address given to it): the finding closes once the evidence is CONFLICT_OPEN_S old and clear_cycles judgments
# have passed, within half an hour, not before
gone_at, closed_after = now, None
for _ in range(30):
    if cycle(CAM) == ["closed"]:
        closed_after = now - STEP_S - gone_at
        break
assert closed_after is not None and e.findings() == [], "closed"
assert macverdict.CONFLICT_OPEN_S <= closed_after <= 30 * 60, closed_after
assert closed_after <= macverdict.CONFLICT_OPEN_S + (H20["params"]["clear_cycles"] + 1) * STEP_S, closed_after
print("check_health_h20_intermittent: ok (closed %d min after the relay left)" % (closed_after // 60))
