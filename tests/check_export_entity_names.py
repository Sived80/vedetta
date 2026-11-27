# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The names of the entities of a device in Home Assistant's registry are written by people ("Ottavia Bluetooth", "Pixel 8 Ottavia
(Wi-Fi)") and nothing in recognition reads them: the export for the developer keeps only how many there are, in every file that carries
the registry (the snapshot in state/, the data file, the debug of the cards). Invented names and documentation addresses."""
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
REG = {"name": "Pixel 8", "name_by_user": False, "manufacturer": "Google, Inc.", "model": None, "area": None, "domains": ["unifi"],
       "entry_titles": [], "observer_titles": [], "sw_version": None, "entity_names": ["Ottavia Bluetooth", "Pixel 8 Ottavia (Wi-Fi)"],
       "entity_domains": ["device_tracker"]}
ha_registry._state["by_mac"] = {"02:00:5e:10:00:77": dict(REG)}; ha_registry._state["by_ip"] = {}
(tmp / "ha_registry.json").write_text(json.dumps({"by_mac": {"02:00:5e:10:00:77": dict(REG)}, "by_ip": {}}), encoding="utf-8")


def zip_of(blob):
    z = zipfile.ZipFile(io.BytesIO(blob))
    return {n: z.read(n) for n in z.namelist()}



f = zip_of(E.build("dev"))
leaks = sorted(n for n, b in f.items() if b"Ottavia" in b)
assert not leaks, "a person's name in the entity names reached the export: " + ", ".join(leaks)
snap = json.loads(f["state/ha_registry.json"])
card = next(iter(snap["by_mac"].values()))
assert card["entity_names"] == 2 and card["entity_domains"] == ["device_tracker"], card
data = json.loads(f["data/ha_registry.json"])
assert next(iter(data["by_mac"].values()))["entity_names"] == 2, data
print("check_export_entity_names: ok")
