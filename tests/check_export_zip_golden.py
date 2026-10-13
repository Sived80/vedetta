"""Golden-master test of export_zip.build_zip (the whole export file): four situations on a fake network - everything present; the history database too big to
include; a corrupt one; nothing flagged and an empty data folder - with data files of every kind (json, broken json, long log, plain text, binary, names that look
like credentials, the mapping file, a sub-folder) must give, entry by entry, exactly the content stored in tests/golden/export_zip.json, written from the code as
it was before the function was split. The manifest is compared without the keys that change at every run (time, python, platform, service report).
Regenerate only on purpose:  ZIP_GOLDEN_UPDATE=1 python tests/check_export_zip_golden.py"""
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

if os.environ.get("PYTHONHASHSEED") != "0":      # names are numbered in the order of sets of strings, which changes with the hash seed: pin it
    sys.exit(subprocess.call([sys.executable] + sys.argv, env={**os.environ, "PYTHONHASHSEED": "0"}))

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()      # never the real folder of the developer: journal, settings and history start empty

import yaml  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import paths  # noqa: E402
from app.export import export_zip as export  # noqa: E402
from app.ha import ha_registry  # noqa: E402
from app.scan import dhcp, mdns_listener  # noqa: E402
from app.state import state  # noqa: E402
from app.storage import devices_config, history as history_mod  # noqa: E402
from app.storage.history import History  # noqa: E402
from golden_text import lf  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "export_zip.json"
VOLATILE = ("created", "python", "platform", "service", "time", "version")


NOW = 1_700_000_000.0
_real_time = time.time


def scenario(name: str, db: str, flagged: bool, files: bool) -> dict:
    time.time = lambda: NOW            # the clock is part of the files (history, journal): it stands still
    try:
        return _scenario(db, flagged, files)
    finally:
        time.time = _real_time


def _scenario(db: str, flagged: bool, files: bool) -> dict:
    tmp = Path(tempfile.mkdtemp())
    paths.DATA_DIR = tmp
    export.paths.DATA_DIR = tmp
    devices_config.DEVICES_PATH = tmp / "devices.yaml"
    (tmp / "devices.yaml").write_text(yaml.safe_dump({"devices": [
        {"id": "d1", "ip": "192.168.77.20", "adapter": "ping", "name": "Giulia's iPad"},
        {"id": "d2", "ip": "192.168.77.31", "adapter": "ping", "name": "salotto-tv-rossi"}]}), encoding="utf-8", newline="\r\n")
    if flagged:
        devices_config.set_override("d2", "focus", "1")
        devices_config.set_override("d1", "focus", "1")
        devices_config.set_override("d1", "focus_note", "The iPad of Giulia at 192.168.77.20 turns off at 3 am")
    now = NOW
    H = History(tmp / "t.db")
    H.record_presence("d1", "192.168.77.20", "f0:18:98:aa:bb:cc", True, now - 3600)
    H.record_presence("d1", "192.168.77.20", "f0:18:98:aa:bb:cc", False, now - 1800)
    history_mod.history = H
    state.devices.clear()
    state.devices["d1"] = {"id": "d1", "ip": "192.168.77.20", "mac": "f0:18:98:aa:bb:cc", "name": "Giulia's iPad", "brand": "Apple", "extra": {}, "scanned_ports": [], "online": True}
    state.devices["d2"] = {"id": "d2", "ip": "192.168.77.31", "mac": "3c:22:fb:11:22:33", "name": "salotto-tv-rossi", "brand": "Samsung", "extra": {}, "scanned_ports": [], "online": False}
    dhcp.seen.clear()
    dhcp.seen["f0:18:98:aa:bb:cc"] = {"hostname": "giulia-ipad", "vendor_class": "", "seen": now}
    mdns_listener.by_mac.clear()
    mdns_listener.by_ip.clear()
    ha_registry._state.update(by_mac={"3c:22:fb:11:22:33": {"name": "salotto-tv-rossi", "area": "Cucina Rossi", "manufacturer": "Samsung"}}, by_ip={}, at=0.0)
    if files:
        (tmp / "settings.json").write_text(json.dumps({"mqtt_password": "hunter2", "note": "Cucina Rossi 192.168.77.20", "nested": {"api_token": "abc", "x": [1, {"secret": "s"}]}}), encoding="utf-8")
        (tmp / "broken.json").write_text("{not json 192.168.77.20", encoding="utf-8")
        (tmp / "app.log").write_text("".join(f"line {i} probe 192.168.77.31 (salotto-tv-rossi) mac 3C:22:FB:11:22:33\n" for i in range(60)), encoding="utf-8", newline="\r\n")
        (tmp / "events.jsonl").write_text("".join('{"n": %d, "ip": "192.168.77.20", "name": "Giulia\'s iPad"}\n' % i for i in range(40)), encoding="utf-8", newline="\r\n")
        (tmp / "notes.txt").write_text("owner Giulia at 192.168.77.20", encoding="utf-8")
        (tmp / "blob.bin").write_bytes(bytes(range(256)) * 3)
        (tmp / "api_key.json").write_text('{"a": 1}', encoding="utf-8")
        (tmp / "user_lang.json").write_text('{"u": "x"}', encoding="utf-8")
        (tmp / export.MAPPING_FILE).write_text('{"old": "mapping"}', encoding="utf-8")
        (tmp / "sub").mkdir()
        (tmp / "sub" / "inner.json").write_text('{"ip": "192.168.77.20"}', encoding="utf-8")
    if db == "ok":
        con = sqlite3.connect(tmp / "vedetta.db")
        con.execute("CREATE TABLE seen (ip TEXT, mac TEXT, name TEXT, ms REAL)")
        con.execute("INSERT INTO seen VALUES ('192.168.77.20', 'f0:18:98:aa:bb:cc', 'Giulia''s iPad', 4.5)")
        con.commit()
        con.close()
    elif db == "corrupt":
        (tmp / "vedetta.db").write_bytes(b"this is not a database" * 50)
    old = (export.MAX_DB_BYTES, export.MAX_LOG_BYTES)
    if db == "big":
        (tmp / "vedetta.db").write_bytes(b"x" * 600)
        export.MAX_DB_BYTES = 100
    export.MAX_LOG_BYTES = 500
    real_anonymize, real_focus_max = export._anonymize_text, devices_config.FOCUS_MAX
    if db == "corrupt":
        def failing(name, text, anon, report=None):
            if name == "data/notes.txt":
                raise export.MaskingFailed("data/notes.txt: email address")
            return real_anonymize(name, text, anon, report)
        export._anonymize_text = failing
        devices_config.FOCUS_MAX = 1
    try:
        blob = export.build_zip()
    finally:
        export.MAX_DB_BYTES, export.MAX_LOG_BYTES = old
        export._anonymize_text, devices_config.FOCUS_MAX = real_anonymize, real_focus_max
    out = {"omitted": list(export.last_omitted), "mapping_file": (tmp / export.MAPPING_FILE).read_text(encoding="utf-8") if (tmp / export.MAPPING_FILE).exists() else None, "entries": {}}
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for n in sorted(z.namelist()):
            raw = z.read(n)
            if n == "manifest.json":
                man = json.loads(raw)
                out["entries"][n] = {k: v for k, v in man.items() if k not in VOLATILE}
            elif n == "data/vedetta.db":
                dbf = tmp / "out.db"
                dbf.write_bytes(raw)
                out["entries"][n] = sqlite3.connect(dbf).execute("SELECT ip, mac, name, ms FROM seen").fetchall()
            else:
                out["entries"][n] = raw.decode("utf-8", "replace")
    state.devices.clear()
    return out


out = {"all": scenario("all", "ok", True, True), "bigdb": scenario("bigdb", "big", False, True), "corrupt": scenario("corrupt", "corrupt", True, True), "empty": scenario("empty", "none", False, False)}
out = lf(json.loads(json.dumps(out, sort_keys=True, default=str)))
if os.environ.get("ZIP_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(out, sort_keys=True, indent=1), encoding="utf-8")
    print("golden written")
want = lf(json.loads(GOLDEN.read_text(encoding="utf-8")))
for sc in want:
    assert sorted(out[sc]["entries"]) == sorted(want[sc]["entries"]), (sc, sorted(out[sc]["entries"]), sorted(want[sc]["entries"]))
    for n in want[sc]["entries"]:
        assert out[sc]["entries"][n] == want[sc]["entries"][n], "%s %s differs: %s" % (sc, n, json.dumps([out[sc]["entries"][n], want[sc]["entries"][n]], default=str)[:600])
    assert out[sc] == want[sc], sc
a = out["all"]["entries"]
assert out["corrupt"]["omitted"] and len(json.loads(out["corrupt"]["entries"]["state/focus.json"])["devices"]) == 1 and "state/journal.json" in a, "scenarios too uniform"
assert "state/focus.json" in a and "data/vedetta.db" in a and "data/blob.bin" not in a and "data/api_key.json" not in a and out["bigdb"]["entries"]["manifest.json"]["notes"], "scenarios too uniform"
print("TUTTO OK")
