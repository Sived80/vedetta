"""Golden-master test of export_engine.prepare (phase 1 of the export: gather, mask, check, fix): five situations on a fake network - the file for the developer;
the same with a text file the masking left readable (it is repaired); with a database row it left readable (repaired in the copy); with a value that cannot be
repaired (the person decides); the file for the person themselves (not masked) - must give exactly the files, the fixed count, the pending list, the manifest
(without the keys that change at every run) and the steps announced, stored in tests/golden/export_prepare.json, written from the code as it was before the
function was split.   Regenerate only on purpose:  PREPARE_GOLDEN_UPDATE=1 python tests/check_export_prepare_golden.py"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

if os.environ.get("PYTHONHASHSEED") != "0":      # names are numbered in the order of sets of strings, which changes with the hash seed: pin it
    sys.exit(subprocess.call([sys.executable] + sys.argv, env={**os.environ, "PYTHONHASHSEED": "0"}))
os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()      # never the real folder of the developer

import yaml  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import paths  # noqa: E402
from app.export import export_engine as engine, export_zip, export_mask  # noqa: E402
from app.ha import ha_registry  # noqa: E402
from app.scan import dhcp, mdns_listener  # noqa: E402
from app.state import state  # noqa: E402
from app.storage import devices_config, history as history_mod  # noqa: E402
from app.storage.history import History  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "export_prepare.json"
VOLATILE = ("created", "python", "platform", "service", "time", "version")
NOW = 1_700_000_000.0
_real_time = time.time


def setup(db_rows: list) -> Path:
    tmp = Path(tempfile.mkdtemp())
    paths.DATA_DIR = tmp
    export_zip.paths.DATA_DIR = tmp
    engine.paths.DATA_DIR = tmp
    devices_config.DEVICES_PATH = tmp / "devices.yaml"
    (tmp / "devices.yaml").write_text(yaml.safe_dump({"devices": [
        {"id": "d1", "ip": "192.168.77.20", "adapter": "ping", "name": "Giulia's iPad"},
        {"id": "d2", "ip": "192.168.77.31", "adapter": "ping", "name": "salotto-tv-rossi"}]}), encoding="utf-8", newline="\r\n")
    devices_config.set_override("d1", "focus", "1")
    devices_config.set_override("d1", "focus_note", "The iPad of Giulia at 192.168.77.20 turns off at 3 am")
    H = History(tmp / "t.db")
    H.record_presence("d1", "192.168.77.20", "f0:18:98:aa:bb:cc", True, NOW - 3600)
    H.record_presence("d1", "192.168.77.20", "f0:18:98:aa:bb:cc", False, NOW - 1800)
    history_mod.history = H
    state.devices.clear()
    state.devices["d1"] = {"id": "d1", "ip": "192.168.77.20", "mac": "f0:18:98:aa:bb:cc", "name": "Giulia's iPad", "brand": "Apple", "extra": {}, "scanned_ports": [], "online": True}
    state.devices["d2"] = {"id": "d2", "ip": "192.168.77.31", "mac": "3c:22:fb:11:22:33", "name": "salotto-tv-rossi", "brand": "Samsung", "extra": {}, "scanned_ports": [], "online": False}
    dhcp.seen.clear()
    dhcp.seen["f0:18:98:aa:bb:cc"] = {"hostname": "giulia-ipad", "vendor_class": "", "seen": NOW}
    mdns_listener.by_mac.clear()
    mdns_listener.by_ip.clear()
    ha_registry._state.update(by_mac={"3c:22:fb:11:22:33": {"name": "salotto-tv-rossi", "area": "Cucina Rossi", "manufacturer": "Samsung"}}, by_ip={}, at=0.0)
    (tmp / "settings.json").write_text(json.dumps({"mqtt_password": "hunter2", "note": "Cucina Rossi 192.168.77.20"}), encoding="utf-8")
    (tmp / "app.log").write_text("".join(f"line {i} probe 192.168.77.31 (salotto-tv-rossi) mac 3C:22:FB:11:22:33\n" for i in range(20)), encoding="utf-8", newline="\r\n")
    (tmp / "notes.txt").write_text("owner Giulia at 192.168.77.20 mail giulia@example.com", encoding="utf-8")
    con = sqlite3.connect(tmp / "vedetta.db")
    con.execute("CREATE TABLE seen (ip TEXT, mac TEXT, name TEXT, ms REAL)")
    for row in db_rows:
        con.execute("INSERT INTO seen VALUES (?, ?, ?, ?)", row)
    con.commit()
    con.close()
    return tmp


def run(dest: str, db_rows: list, skip_text: tuple = (), skip_db: bool = False, unfixable: bool = False) -> dict:
    time.time = lambda: NOW
    tmp = setup(db_rows)
    real_text, real_db, real_repair = engine._mask_text, engine._mask_db, engine._repair_file
    steps: list = []
    engine._mask_text = lambda name, text, anon: text if name in skip_text else real_text(name, text, anon)
    export_mask._mask_text = engine._mask_text
    if skip_db:
        engine._mask_db = lambda path, anon: None
        export_mask._mask_db = engine._mask_db
    if unfixable:
        engine._repair_file = lambda name, text, anon: (text, 0, [("email address", "giulia@example.com", "line 1"), ("email address", "giulia@example.com", "line 2"), ("name", "Giulia", "line 3")])
        export_mask._repair_file = engine._repair_file
    try:
        p = engine.prepare(dest, progress=steps.append)
    finally:
        time.time = _real_time
        engine._mask_text, engine._mask_db, engine._repair_file = real_text, real_db, real_repair
        export_mask._mask_text, export_mask._mask_db, export_mask._repair_file = engine._mask_text, engine._mask_db, engine._repair_file
    try:
        files = {}
        for name, entry in sorted(p.files.items()):
            if entry[0] == "text":
                files[name] = entry[1]
            else:
                files[name] = sqlite3.connect(entry[1]).execute("SELECT ip, mac, name, ms FROM seen").fetchall()
        man = {k: v for k, v in p.manifest.items() if k not in VOLATILE}
        out = {"files": files, "fixed": p.fixed, "pending": p.pending, "manifest": man, "steps": steps, "anon": p.anon is not None}
    finally:
        p.close()
    state.devices.clear()
    return out


LEAK_ROW = ("192.168.77.20", "f0:18:98:aa:bb:cc", "Giulia's iPad", 4.5)
out = {
    "dev": run("dev", [LEAK_ROW]),
    "text_left": run("dev", [LEAK_ROW], skip_text=("data/notes.txt", "data/app.log")),
    "db_left": run("dev", [LEAK_ROW, ("192.168.77.31", "3c:22:fb:11:22:33", "salotto-tv-rossi", 1.0)], skip_db=True),
    "unfixable": run("dev", [LEAK_ROW], skip_text=("data/notes.txt",), unfixable=True),
    "me": run("me", [LEAK_ROW]),
}
out = json.loads(json.dumps(out, sort_keys=True, default=str))
if os.environ.get("PREPARE_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(out, sort_keys=True, indent=1), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
for sc in want:
    assert out[sc] == want[sc], "%s differs: %s" % (sc, json.dumps([out[sc], want[sc]], default=str)[:700])
assert out["text_left"]["fixed"] > 0 and out["db_left"]["fixed"] > 0 and out["unfixable"]["pending"] and not out["dev"]["pending"], "scenarios too uniform"
assert out["me"]["steps"] == ["collect"] and out["dev"]["steps"][:3] == ["collect", "mask", "check"] and "fix" in out["text_left"]["steps"], out["me"]["steps"]
print("TUTTO OK")
