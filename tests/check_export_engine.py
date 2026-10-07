"""The new export: for the person ("me": nothing masked, credentials still replaced) and for the developer ("dev": masked, checked,
fixed, and what cannot be fixed is decided by the person), limited to a period, with an estimate of how big it will be."""
import io
import json
import os
import sqlite3
import sys
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.export import anonymize, export_zip as export, export_engine as E
from app.storage import devices_config
from app.scan import dhcp, mdns_listener
from app.ha import ha_registry
from app import paths  # noqa: E402
from app.storage import history as history_mod  # noqa: E402
from app.storage.history import History  # noqa: E402
from app.state import state  # noqa: E402

tmp = Path(tempfile.mkdtemp())
paths.DATA_DIR = tmp
devices_config.DEVICES_PATH = tmp / "devices.yaml"
(tmp / "devices.yaml").write_text(yaml.safe_dump({"devices": [{"id": "d1", "ip": "192.168.77.20", "adapter": "ping", "name": "Giulia's iPad"}]}), encoding="utf-8")
iso = lambda ts: datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")      # noqa: E731
D = E.day_start
now = time.time()

# --- a log over three days, a journal, a database
(tmp / "dashboard.log").write_text("\n".join([
    f"{iso(D(3) + 3600)}\tINFO\tthree days ago 192.168.77.20",
    f"{iso(D(2) + 3600)}\tINFO\ttwo days ago",
    f"{iso(D(1) + 3600)}\tINFO\tyesterday owner Giulia's iPad",
    "    traceback row of yesterday",
    f"{iso(now - 10)}\tWARNING\tnow a.b@example.com and c.d@example.com",
]) + "\n", encoding="utf-8")
(tmp / "journal.jsonl").write_text("\n".join(json.dumps(x) for x in ({"ts": D(3) + 5, "k": "old"}, {"ts": D(1) + 5, "k": "in"}, {"ts": now - 5, "k": "now"})) + "\n", encoding="utf-8")
(tmp / "settings.json").write_text(json.dumps({"mqtt_password": "hunter2", "note": "kitchen 192.168.77.20", "mail": "c.d@example.com"}), encoding="utf-8")
H = History(tmp / "vedetta.db")
for off, online in ((3, 1), (2, 0), (1, 1)):
    H.record_presence("d1", "192.168.77.20", "f0:18:98:aa:bb:cc", bool(online), D(off) + 100)
H.record_presence("d1", "192.168.77.20", "f0:18:98:aa:bb:cc", False, now - 5)
H.mac_takeover_add(D(3) + 50, "d1", "192.168.77.20", "a", "b", {}, {}, {}, True)
H._db.execute("INSERT INTO known_macs (mac, first_seen, ip, vendor, hostname, status) VALUES ('f0:18:98:aa:bb:cc', ?, '192.168.77.20', 'Apple', 'c.d@example.com', 'known')", (D(10),))
H._db.commit()
history_mod.history = H
state.devices.clear()
state.devices["d1"] = {"id": "d1", "ip": "192.168.77.20", "mac": "f0:18:98:aa:bb:cc", "name": "Giulia's iPad", "brand": "Apple", "extra": {}, "scanned_ports": [], "online": True}
dhcp.seen.clear(); mdns_listener.by_mac.clear(); mdns_listener.by_ip.clear()
ha_registry._state["by_mac"] = {}; ha_registry._state["by_ip"] = {}


def zip_of(blob):
    z = zipfile.ZipFile(io.BytesIO(blob))
    return {n: z.read(n) for n in z.namelist()}


def rows(files, table):
    f = tmp / "check.db"
    f.write_bytes(files["data/vedetta.db"])
    return sqlite3.connect(f).execute(f"SELECT * FROM {table}").fetchall()


# --- the period
since, until = E.bounds(1, 0)
assert since == D(1) and abs(until - time.time()) < 5 and E.bounds(None, None) == (None, None) and E.bounds(3, 2)[1] == D(1)
kept = E.filter_log((tmp / "dashboard.log").read_text(encoding="utf-8"), since, until)
assert "three days" not in kept and "two days" not in kept and "yesterday" in kept and "traceback row" in kept and "a.b@" in kept
big = "\n".join(f"{iso(now - 5)}\tINFO\t{'x' * 100}" for _ in range(50))
assert len(E.filter_log(big, 0, now + 1, cap=1000).encode()) <= 1000
assert E.filter_jsonl((tmp / "journal.jsonl").read_text(encoding="utf-8"), since, until).count("\n") == 1

# --- for me: nothing is masked, a credential still is
f = zip_of(E.build("me", 1, 0))
man = json.loads(f["manifest.json"])
assert man["dest"] == "me" and "check" not in man and not (tmp / export.MAPPING_FILE).exists()
assert b"192.168.77.20" in f["data/settings.json"] and b"Giulia" in f["data/dashboard.log"] and b"f0:18:98:aa:bb:cc" in f["state/devices_compact.json"].lower()
assert b"hunter2" not in f["data/settings.json"] and b'"***"' in f["data/settings.json"]
assert b"three days" not in f["data/dashboard.log"] and b'"old"' not in f["data/journal.jsonl"] and b'"in"' in f["data/journal.jsonl"]
pres = rows(f, "presence_events")
assert [r[4] for r in pres] == [0, 1, 0] and len(pres) == 3, pres          # the last event before the period (state at the start), then the period
assert rows(f, "mac_takeover") == [] and len(rows(f, "known_macs")) == 1
full = zip_of(E.build("me"))                                               # no period: the whole history
assert len(rows(full, "presence_events")) == 4 and b"three days" in full["data/dashboard.log"]

# --- for the developer: masked
f = zip_of(E.build("dev", 1, 0))
man = json.loads(f["manifest.json"])
assert man["dest"] == "dev" and man["check"]["fixed"] == 0 and man["period"]["all"] is False and (tmp / export.MAPPING_FILE).exists()
for name, raw in f.items():
    if name == "data/vedetta.db":
        continue
    text = raw.decode("utf-8")
    for leak in ("192.168.77.", "f0:18:98:aa", "Giulia", "hunter2"):
        assert leak not in text, (name, leak)
assert b"10.0.0.20" in f["data/settings.json"] and b"iPad-1" in f["data/dashboard.log"]
assert [r[4] for r in rows(f, "presence_events")] == [0, 1, 0]


# --- the check finds something the masking missed: fixed by itself, or decided by the person
class Weak(anonymize.Anonymizer):
    """Leaves a.b@example.com in long text (a miss the repair can still fix) and c.d@example.com everywhere (it cannot)."""
    def text(self, s):
        keep = ["c.d@example.com"] + (["a.b@example.com"] if len(s) > 40 else [])
        for i, k in enumerate(keep):
            s = s.replace(k, f"@@{i}@@")
        s = super().text(s)
        for i, k in enumerate(keep):
            s = s.replace(f"@@{i}@@", k)
        return s


real = anonymize.Anonymizer
export.anonymize.Anonymizer = Weak
try:
    seen = []
    p = E.prepare("dev", 1, 0, progress=seen.append)
    assert seen == ["collect", "mask", "check", "fix"], seen
    assert p.fixed >= 1, p.fixed
    left = {(i["file"], i["kind"], i["value"]) for i in p.pending}
    assert left == {("data/dashboard.log", "email address", "c.d@example.com"), ("data/settings.json", "email address", "c.d@example.com"),
                    ("data/vedetta.db", "email address", "c.d@example.com")}, left
    assert all(i["where"] for i in p.pending) and [i["id"] for i in p.pending] == list(range(len(p.pending)))
    assert "a.b@example.com" not in p.files["data/dashboard.log"][1]            # fixed by itself
    ids = {i["file"]: i["id"] for i in p.pending}
    f = zip_of(E.finish(p, {ids["data/dashboard.log"]: "keep"}))                # keep one, the others get the default (remove)
    p.close()
    assert b"c.d@example.com" in f["data/dashboard.log"] and b"c.d@example.com" not in f["data/settings.json"] and b"[removed]" in f["data/settings.json"]
    json.loads(f["data/settings.json"])                                          # still valid JSON
    assert b"c.d@example.com" not in f["data/vedetta.db"] and b"[removed]" in f["data/vedetta.db"]
    man = json.loads(f["manifest.json"])
    assert man["check"]["kept"] == 1 and man["check"]["removed"] == 2 and man["check"]["fixed"] >= 1, man["check"]
    # everything chosen as "keep" leaves everything as it was
    p = E.prepare("dev", 1, 0)
    f = zip_of(E.finish(p, default="keep"))
    p.close()
    assert b"c.d@example.com" in f["data/settings.json"] and json.loads(f["manifest.json"])["check"]["removed"] == 0
finally:
    export.anonymize.Anonymizer = real

# --- how big it will be
est = E.estimate()
assert len(est["daily"]) == E.HORIZON_DAYS and est["limit"] == E.LIMIT_BYTES and est["base"] > 0 and est["flagged"] == 0
assert est["daily"][0] > 0 and est["daily"][1] > 0 and est["daily"][2] > 0 and sum(est["daily"][4:]) == 0, est["daily"][:6]    # the log and the events of those days
print("TUTTO OK")
