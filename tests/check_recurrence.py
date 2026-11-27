# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""How a device comes and goes over 30 days (analysis/recurrence.py): the class is worked out on the history of THIS device (a device
that appeared 3 days ago is "observing", one that appeared 10 days ago and was there every day is "stable", not "occasional" against
a month it was not there for); a day is active when the device was online for some of it, in the local time of Home Assistant; the
strip is read from today. The route answers for a card and 404 for an unknown one.
    python tests/check_recurrence.py"""
import os
import sys
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.analysis import recurrence as rc  # noqa: E402

TZ = ZoneInfo("Europe/Rome")
DAY = 86400
NOW = datetime(2026, 11, 16, 18, 0, tzinfo=TZ).timestamp()


def at(days_ago, hour, minutes=30):
    return datetime.fromtimestamp(NOW - days_ago * DAY, TZ).replace(hour=hour, minute=0, second=0).timestamp(), minutes * 60


def seg(days_ago, hour=12, minutes=30, online=True):
    t, d = at(days_ago, hour, minutes)
    return {"from": t, "to": t + d, "online": online}


# 1) the classes, with their thresholds (8/30 and 21/30 of the device's own history)
assert rc.classify(5, 3) == rc.OBSERVING and rc.classify(1, 30) == rc.ONCE
assert rc.classify(7, 30) == rc.OCCASIONAL_K and rc.classify(8, 30) == rc.RECURRING
assert rc.classify(20, 30) == rc.RECURRING and rc.classify(21, 30) == rc.STABLE_K
assert rc.classify(8, 10) == rc.STABLE_K                                     # 8 of its 10 days: stable

# 2) a device seen every day since 10 days ago: stable (not occasional against 30 days)
segs = [seg(d) for d in range(10)]
r = rc.recurrence(segs, at(9, 8)[0], NOW, TZ)
assert r["class"] == rc.STABLE_K and r["active_days"] == 10 and r["history_days"] == 10, r
assert len(r["strip"]) == 30 and r["strip"][-1] is True and r["strip"][-10:] == [True] * 10 and r["strip"][0] is False

# 3) three days of history: observing
assert rc.recurrence([seg(0), seg(1)], at(2, 8)[0], NOW, TZ)["class"] == rc.OBSERVING

# 4) a whole month known, seen on 3 days: occasional; offline segments do not count
segs = [seg(2), seg(15), seg(28), seg(5, online=False), seg(6, online=False)]
r = rc.recurrence(segs, NOW - 60 * DAY, NOW, TZ)
assert r["class"] == rc.OCCASIONAL_K and r["active_days"] == 3 and r["history_days"] == 30, r

# 5) a segment across midnight touches both days; one older than the window is not counted
cross = {"from": at(3, 23)[0], "to": at(3, 23)[0] + 2 * 3600, "online": True}
assert len(rc.active_days([cross], TZ)) == 2
assert rc.recurrence([seg(40)], NOW - 60 * DAY, NOW, TZ)["active_days"] == 0
assert rc.window_start(NOW, TZ) == datetime(2026, 10, 18, 0, 0, tzinfo=TZ).timestamp()

# 6) the route
from fastapi.testclient import TestClient  # noqa: E402
from app import main  # noqa: E402
from app.state import state  # noqa: E402
state.devices["nas"] = {"id": "nas", "ip": "10.0.0.5", "online": True}
client = TestClient(main.app)
r = client.get("/api/ha/recurrence/nas")
assert r.status_code == 200 and set(r.json()) == {"class", "active_days", "history_days", "strip"}, r.text
assert client.get("/api/ha/recurrence/ghost").status_code == 404
print("check_recurrence: ok")
