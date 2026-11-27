# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""While Vedetta is off nothing is known (storage/history_presence.py): a card online before a stop used to stay online across the whole
pause, a night of power cut included, and the bars and the percentage said so. Now every run of the service is recorded (start and
last sign of life, every minute) and the holes between two runs are cut out of the segments: unknown time, neither online nor offline,
and the percentage is worked out on the known time only. A restart shorter than GAP_MIN_S is not a hole.
    python tests/check_presence_gaps.py"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.storage import history_presence as hp  # noqa: E402
from app.storage.history import History  # noqa: E402

# 1) pure: the holes, and the segments without them
runs = [[0, 1000], [1060, 5000], [9000, 12000]]                 # a restart of 60 s (no hole), then 4000 s off
assert hp.gaps_between(runs, 0, 20000) == [(5000, 9000)]
assert hp.gaps_between(runs, 6000, 7000) == [(6000, 7000)]       # clipped to the window
assert hp.gaps_between([], 0, 10) == [] and hp.gaps_between([[0, 5]], 0, 10) == []
segs = [{"from": 0, "to": 12000, "online": True}]
assert hp.cut_gaps(segs, [(5000, 9000)]) == [{"from": 0, "to": 5000, "online": True}, {"from": 9000, "to": 12000, "online": True}]
assert hp.cut_gaps([{"from": 6000, "to": 7000, "online": False}], [(5000, 9000)]) == []
assert hp.cut_gaps(segs, []) == segs

# 2) the database: a card online at 100, Vedetta off from 5000 to 9000, offline at 10000
h = History(Path(tempfile.mkdtemp()) / "h.db")
h.service_run_begin(0)
for t in range(60, 5001, 60):
    h.service_run_beat(t)
h.record_presence("nas", "10.0.0.5", None, True, 100)
h.service_run_begin(9000)
h.service_run_beat(9060)
h.record_presence("nas", "10.0.0.5", None, False, 10000)
r = h.presence_segments("nas", 0, 12000)
assert [(s["from"], s["to"], s["online"]) for s in r["segments"]] == [(100, 4980, True), (9000, 10000, True), (10000, 12000, False)], r["segments"]
assert r["online_pct"] == round(100 * (4880 + 1000) / (4880 + 1000 + 2000), 1), r["online_pct"]
# before: the whole pause counted as online
before = hp._segments_report(hp._segments_from_events({"online": 1}, [{"online": 0, "ts": 10000}], 100, 12000), 100, 12000)
assert before["online_pct"] > r["online_pct"]

# 3) a damaged record of the runs is no hole at all (never an error)
h.meta_set(hp.RUNS_KEY, "{oops")
assert h.service_gaps(0, 12000) == [] and h.presence_segments("nas", 0, 12000)["segments"]
print("check_presence_gaps: ok")
