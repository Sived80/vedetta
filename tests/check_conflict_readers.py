"""The IP conflict in one place (1.0 step P3): the alert "duplicate IP" and the network doctor (H20 and its page) read the conflicts of the single verdict
(macverdict.conflicts: judged in time by macclassify, going on while the last evidence is recent), not the last ARP scan any more.
Proved here: the alert is sent once for each address and set of MACs while the app runs (as before: a conflict that ends and comes back is not sent again,
a new MAC on the address is), at its place in the cycle; and - with a spy on the source - that no file of the app names the old snapshot of the scan
(arp_conflicts, its filter _real_conflicts) and that the readers of the conflicts are health_view and report_ip_conflicts, both through macverdict.conflicts.
Every address and MAC is made up."""
import os
import re
import sys
import tempfile
import time
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import macverdict, state as state_mod  # noqa: E402

APP = Path(__file__).resolve().parent.parent / "vedetta" / "app"
A, B, C = "02:00:00:00:60:01", "02:00:00:00:60:02", "02:00:00:00:60:03"


def conflict(ip, macs, age_s=0.0):
    return {"ip": ip, "macs": macs, "first_seen": 0.0, "last_evidence": time.time() - age_s}


st = state_mod.DeviceState()
sent: list = []
st.emit_alert = lambda text, key, **params: sent.append((text, key, params))

# nothing going on, nothing sent
macverdict.refresh_conflicts([conflict("10.0.60.5", [A, B], age_s=macverdict.CONFLICT_OPEN_S + 60)])
st.report_ip_conflicts()
assert sent == [], "a conflict that is over is not reported"

# a conflict going on: one alert, the same words and parameters as before
macverdict.refresh_conflicts([conflict("10.0.60.5", [A, B])])
st.report_ip_conflicts()
st.report_ip_conflicts()
assert sent == [(f"IP duplicato 10.0.60.5: risponde da {A}, {B}", "alert.ip_conflict", {"ip": "10.0.60.5", "macs": f"{A}, {B}"})], sent

# it ends and comes back while the app runs: not sent again; a third MAC on the address is a new alert
macverdict.refresh_conflicts([])
st.report_ip_conflicts()
macverdict.refresh_conflicts([conflict("10.0.60.5", [A, B])])
st.report_ip_conflicts()
assert len(sent) == 1, sent
macverdict.refresh_conflicts([conflict("10.0.60.5", [A, B]), conflict("10.0.60.5", [A, C])])
st.report_ip_conflicts()
assert len(sent) == 2 and sent[1][2] == {"ip": "10.0.60.5", "macs": f"{A}, {B}, {C}"}, sent

# after a restart (a new state) the alert of a conflict going on is sent once more, as before
st2 = state_mod.DeviceState()
st2.emit_alert = lambda text, key, **params: sent.append((text, key, params))
st2.report_ip_conflicts()
assert len(sent) == 3, sent
macverdict.refresh_conflicts([])

# SPY on the source: the snapshot of the last scan is gone, and every reader of the conflicts goes through the single verdict
OLD = re.compile(r"\barp_conflicts\b|\b_real_conflicts\b")
named, readers = [], []
for f in APP.rglob("*.py"):
    text = f.read_text(encoding="utf-8")
    rel = f.relative_to(APP).as_posix()
    named += [rel for _ in OLD.finditer(text)]
    readers += [rel for _ in re.finditer(r"macverdict\.conflicts\(", text)]
assert named == [], "the old snapshot of the scan is named in: " + repr(named)
assert sorted(set(readers)) == ["ha/health_view.py", "identity_upkeep.py"], readers
upkeep = (APP / "identity_upkeep.py").read_text(encoding="utf-8")
body = upkeep[upkeep.index("def report_ip_conflicts"):upkeep.index("    @staticmethod", upkeep.index("def report_ip_conflicts"))]
assert "macverdict.conflicts(" in body, "the alert reads the single verdict"
print("TUTTO OK")
