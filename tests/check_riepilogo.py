"""tools/riepilogo_report.py: reads a report (a zip in memory), finds the weak devices, the history and the log, and never needs the key for a plain zip."""
import io
import json
import os
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import riepilogo_report as R  # noqa: E402

tmp = Path(tempfile.mkdtemp()) / "v.db"
con = sqlite3.connect(tmp)
con.executescript("""CREATE TABLE presence_events (id INTEGER PRIMARY KEY, device_id TEXT, ip TEXT, mac TEXT, online INTEGER, ts REAL);
CREATE TABLE scans (id INTEGER PRIMARY KEY, device_id TEXT, ts REAL, result_json TEXT);
CREATE TABLE mac_takeover (id INTEGER PRIMARY KEY, ts REAL, device_id TEXT, ip TEXT, old_mac TEXT, new_mac TEXT, new_known INTEGER);
CREATE TABLE mac_memory (mac TEXT PRIMARY KEY);""")
con.executemany("INSERT INTO presence_events (device_id, ip, mac, online, ts) VALUES (?,?,?,?,?)", [("scan-a", "10.0.0.5", "aa:bb:cc:00:00:01", 1, 1791300000), ("scan-a", "10.0.0.5", "aa:bb:cc:00:00:02", 0, 1791300100)])
con.execute("INSERT INTO mac_takeover (ts, device_id, ip, old_mac, new_mac, new_known) VALUES (1791300050, 'scan-a', '10.0.0.5', 'x', 'y', 1)")
con.commit(); con.close()
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    z.writestr("manifest.json", json.dumps({"version": "0.4.3", "created": "x", "time": {"utc_offset": "+0200", "night_hour": 3}, "omitted": []}))
    z.writestr("state/devices_compact.json", json.dumps([
        {"id": "scan-a", "name": "iPhone-1", "ip": "10.0.0.5", "mac": "AA", "type": "phone", "brand": "Apple", "online": True},
        {"id": "scan-b", "name": "10.0.0.9", "ip": "10.0.0.9", "mac": None, "type": "generic", "brand": None, "online": False}]))
    z.writestr("state/evidence.json", json.dumps({"scan-a": {"name": {"certainty": 70}, "brand": {"certainty": 90}, "group": {"certainty": 80}}, "scan-b": {"name": {"certainty": 0, "basis": "ip"}, "brand": {"certainty": 0}, "group": {"certainty": 0}}}))
    z.writestr("data/vedetta.db", tmp.read_bytes())
    z.writestr("state/focus.json", json.dumps({"days": 14, "devices": [{"id": "scan-a", "name": "iPhone-1", "note": "turns on at 6", "card": {"type": "phone", "brand": "Apple"},
        "evidence": {"group": {"certainty": 80}}, "history": {"presence": [{}, {}], "mac_changes": [{}], "macs": [{}]}}]}))
    z.writestr("data/dashboard.log", "2026-10-07T03:00:00+02:00\tWARNING\tHost-timeout 30s su 10.0.0.5\n2026-10-07T03:01:00+02:00\tINFO\tok\n")
z = zipfile.ZipFile(io.BytesIO(buf.getvalue()))
d = R.digest(z)
assert d["devices"]["total"] == 2 and d["devices"]["online"] == 1 and d["devices"]["by_group"] == {"phone": 1, "generic": 1}, d["devices"]
assert [w["id"] for w in d["weak"]] == ["scan-b"] and d["ip_named"] == 1 and d["no_mac"] == ["10.0.0.9"], d["weak"]
assert d["history"]["mac_changes_total"] == 1 and d["history"]["several_macs"] == [("scan-a", 2)], d["history"]
assert d["log"]["levels"] == {"WARNING": 1, "INFO": 1} and d["log"]["top_problems"][0][1] == 1, d["log"]
f = d["focus"][0]
assert f["name"] == "iPhone-1" and f["note"] == "turns on at 6" and f["events"] == 2 and f["mac_changes"] == 1 and f["certainty"]["group"] == 80, f
assert R.card(z, "iPhone-1")["matches"][0]["card"]["brand"] == "Apple" and R.card(z, "9")["matches"][0]["card"]["id"] == "scan-b"
big = zipfile.ZipFile(io.BytesIO(buf.getvalue()))
R.MAX_FILE = 10
assert R.read(big, "state/devices_compact.json") is None          # a file above the limit is not read
print("TUTTO OK")
