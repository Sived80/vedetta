"""The findings of the network health on disk (storage/history_health.py): a finding is written once and then updated (same rule, subject and first sight = same row), a closed one keeps its end, the list is newest first, an old one is pruned with
the rest of the history, and the evidence holds counts only. And the view (ha/health_view.py) writes what the judge has found after each judgment, shadow included, so a restart does not lose the record."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import health_view as hv  # noqa: E402
from app.health.engine import Engine  # noqa: E402
from app.health import matrix  # noqa: E402
from app.storage.history import History  # noqa: E402

NOW = time.time()
DAY = 86400.0
db = History(Path(tempfile.mkdtemp()) / "v.db")


def row(**over):
    base = {"rule": "H20", "subject": "lan", "state": "active", "severity": "warning", "first_seen": NOW - 100, "last_seen": NOW - 50, "hits": 3, "evidence": {"ips": 1, "macs": 2}, "shadow": True}
    return {**base, **over}


# --- write, then update the same finding: one row
db.record_finding(**row())
db.record_finding(**row(last_seen=NOW, hits=5))
got = db.health_findings(NOW - DAY)
assert len(got) == 1 and got[0]["hits"] == 5 and got[0]["last_seen"] == NOW and got[0]["shadow"] is True and got[0]["evidence"] == {"ips": 1, "macs": 2}, got

# --- closing keeps the row and says so
db.record_finding(**row(state="closed", last_seen=NOW + 10))
got = db.health_findings(NOW - DAY)
assert len(got) == 1 and got[0]["state"] == "closed", got

# --- a new episode of the same problem is another row, the newest first
db.record_finding(**row(first_seen=NOW + 100, last_seen=NOW + 100, hits=1, state="tentative"))
got = db.health_findings(NOW - DAY)
assert [g["state"] for g in got] == ["tentative", "closed"], got

# --- an old one is pruned with the history, a recent one stays
db.record_finding(**row(subject="old", first_seen=NOW - 100 * DAY, last_seen=NOW - 100 * DAY))
assert len(db.health_findings(NOW - 200 * DAY)) == 3
db.prune_health()
assert {g["subject"] for g in db.health_findings(NOW - 200 * DAY)} == {"lan"}, "the finding older than the retention is pruned"

# --- no address or name goes to the disk
raw = json.dumps(db.health_findings(NOW - DAY))
assert "192.168" not in raw and "aa:bb" not in raw

# --- the view writes after each judgment (shadow included) through a function that is handed in
saved = []
engine = Engine([dict(matrix.load()[0], status="shadow")])
signals = {"conflicts": {"192.168.1.20": ["aa:bb:cc:00:00:01", "aa:bb:cc:00:00:02"]}}
hv.judge_once(engine, signals, NOW, record=lambda **kw: saved.append(kw))
assert [(s["rule"], s["state"], s["shadow"]) for s in saved] == [("H20", "tentative", True)], saved
hv.judge_once(engine, signals, NOW + 120, record=lambda **kw: saved.append(kw))
assert saved[-1]["state"] == "active" and saved[-1]["hits"] == 2, saved[-1]
saved.clear()
for step in range(1, 4):
    hv.judge_once(engine, {"conflicts": {}}, NOW + 240 + step, record=lambda **kw: saved.append(kw))
assert saved and saved[-1]["state"] == "closed", "the closing is written too: %s" % saved
assert all("192.168" not in json.dumps(s) for s in saved)

print("check_health_store OK")
