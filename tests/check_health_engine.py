"""The judge of the network-health rules (health/engine.py) for the first row, the IP conflict: a conflict is only a «tentative» until it is seen for min_cycles judgments in a row, it becomes «active», it is closed after clear_cycles judgments without it,
and one flicker does not open anything. The evidence never holds an address or a name. A rule in draft is not judged. Pure: the signals are handed in."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.health import detectors, engine  # noqa: E402

ROW = {"id": "H20", "family": "conflict", "params": {"min_cycles": 2, "clear_cycles": 3}, "signals": ["ARP"], "scope": "live", "class": "configuration", "severity": "warning",
       "message_key": "health.h20", "remedy_key": "health.h20.remedy", "detectability": "D1", "status": "shadow", "since": "next",
       "existence": {"grade": "A", "sources": [{"title": "IPv4 Address Conflict Detection", "link": "https://www.rfc-editor.org/rfc/rfc5227", "verified": True}]}}
CONFLICT = {"conflicts": {"192.168.1.20": ["aa:bb:cc:00:00:01", "aa:bb:cc:00:00:02"]}}
QUIET = {"conflicts": {}}

# --- the detector alone: nothing in, nothing out; one conflict gives one piece of evidence with counts only
assert detectors.conflict(QUIET, ROW["params"]) == []
found = detectors.conflict(CONFLICT, ROW["params"])
assert len(found) == 1 and found[0].subject == "lan" and found[0].data == {"ips": 1, "macs": 2}, found

# --- the judge
e = engine.Engine([ROW])
assert e.judge(QUIET, 0) == [] and e.findings() == []

changes = e.judge(CONFLICT, 10)
assert [(c.finding.state, c.change) for c in changes] == [("tentative", "opened")], "the first sight is only a tentative"
changes = e.judge(CONFLICT, 20)
assert [(c.finding.state, c.change) for c in changes] == [("active", "raised")], "the second one in a row makes it active"
assert e.judge(CONFLICT, 30) == [], "nothing changes while it goes on"
active = e.findings()[0]
assert active.hits == 3 and active.first_seen == 10 and active.last_seen == 30 and active.shadow is True and active.severity == "warning"
text = repr(active.evidence) + active.subject
assert "192.168" not in text and "aa:bb" not in text, "the evidence must hold counts only: %s" % text

assert e.judge(QUIET, 40) == [] and e.judge(QUIET, 50) == [], "two quiet judgments are not enough to close it"
changes = e.judge(QUIET, 60)
assert [(c.finding.state, c.change) for c in changes] == [("closed", "closed")] and e.findings() == [], "the third quiet one closes it"

# --- one flicker never opens an active finding; a quiet judgment in between starts the count again
e = engine.Engine([ROW])
e.judge(CONFLICT, 0)
e.judge(QUIET, 10)
e.judge(QUIET, 20)
dropped = e.judge(QUIET, 30)
assert e.findings() == [] and [(c.change, c.finding.state) for c in dropped] == [("dropped", "dropped")], "a tentative that is not seen again goes away, and says so"
e.judge(CONFLICT, 40)
assert [f.state for f in e.findings()] == ["tentative"] and e.findings()[0].hits == 1, "it counts from the start"

# --- a rule that needs one sight only is active at once
once = dict(ROW, params={"min_cycles": 1, "clear_cycles": 2})
e = engine.Engine([once])
assert [(c.change, c.finding.state) for c in e.judge(CONFLICT, 0)] == [("raised", "active")]

# --- a rule in draft is not judged
draft = dict(ROW, status="draft")
e = engine.Engine([draft])
assert e.judge(CONFLICT, 0) == [] and e.findings() == []

# --- a rule that fails does not stop the others
boom = dict(ROW, id="H21", family="conflict")
e = engine.Engine([ROW, boom])
assert len(e.judge({"conflicts": 7}, 0)) == 0, "unreadable signals give no finding, no crash"

print("check_health_engine OK")
