"""Section "device under examination" of the export: a flagged device goes in state/focus.json with its card, evidence,
history (presence, MAC changes, MACs) and the person's note, all anonymised like the rest; nothing flagged = no file."""
import io
import json
import os
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.storage import devices_config
from app.scan import dhcp, mdns_listener
from app.export import export_zip as export
from app.ha import ha_registry
from app import paths  # noqa: E402
from app.storage import history as history_mod  # noqa: E402
from app.storage.history import History  # noqa: E402
from app.state import state  # noqa: E402

tmp = Path(tempfile.mkdtemp())
paths.DATA_DIR = tmp
export.paths.DATA_DIR = tmp
devices_config.DEVICES_PATH = tmp / "devices.yaml"
now = time.time()
(tmp / "devices.yaml").write_text(yaml.safe_dump({"devices": [
    {"id": "d1", "ip": "192.168.77.20", "adapter": "ping", "name": "Giulia's iPad"},
    {"id": "d2", "ip": "192.168.77.31", "adapter": "ping", "name": "salotto-tv-rossi"}]}), encoding="utf-8")

# the flag is a manual choice kept in devices.yaml, with a note
assert devices_config.set_override("d1", "focus", "1")["focus"] == "1"
devices_config.set_override("d1", "focus_note", "The iPad of Giulia at 192.168.77.20 turns off at 3 am")
cfg = {d["id"]: d for d in devices_config.load_devices()}
assert cfg["d1"]["focus"] == "1" and "Giulia" in cfg["d1"]["focus_note"] and "focus" not in cfg["d2"]

H = History(tmp / "t.db")
H.record_presence("d1", "192.168.77.20", "f0:18:98:aa:bb:cc", True, now - 3600)
H.record_presence("d1", "192.168.77.20", "f0:18:98:aa:bb:cc", False, now - 1800)
H.mac_memory_set("f0:18:98:aa:bb:cc", "d1", "192.168.77.20", {"name": "Giulia's iPad", "brand": "Apple", "grp": "phone", "mobile_score": 7}, now - 3600)
H.mac_takeover_add(now - 900, "d1", "192.168.77.20", "aa:bb:cc:00:00:01", "f0:18:98:aa:bb:cc", {"name": "Giulia's iPad", "brand": "Apple", "grp": "phone"}, {}, {}, True)
H.record_presence("d2", "192.168.77.31", "3c:22:fb:11:22:33", True, now - 100)
f = H.device_focus("d1", now - 86400)
assert len(f["presence"]) == 2 and f["presence"][0]["online"] == 0 and len(f["mac_changes"]) == 1 and f["macs"][0]["brand"] == "Apple", f
assert H.device_focus("d1", now + 5)["presence"] == []                      # outside the period nothing
history_mod.history = H

state.devices.clear()
state.devices["d1"] = {"id": "d1", "ip": "192.168.77.20", "mac": "f0:18:98:aa:bb:cc", "name": "Giulia's iPad", "brand": "Apple", "extra": {}, "scanned_ports": [], "online": True}
state.devices["d2"] = {"id": "d2", "ip": "192.168.77.31", "mac": "3c:22:fb:11:22:33", "name": "salotto-tv-rossi", "brand": "Samsung", "extra": {}, "scanned_ports": [], "online": False}
dhcp.seen.clear(); mdns_listener.by_mac.clear(); mdns_listener.by_ip.clear()
ha_registry._state["by_mac"] = {}; ha_registry._state["by_ip"] = {}
(tmp / "vedetta.db").write_bytes(b"")

with zipfile.ZipFile(io.BytesIO(export.build_zip())) as z:
    assert "state/focus.json" in z.namelist(), z.namelist()
    text = z.read("state/focus.json").decode("utf-8")
    man = json.loads(z.read("manifest.json"))
focus = json.loads(text)
assert [x["id"] for x in focus["devices"]] != [] and len(focus["devices"]) == 1 and man["focus"] == {"devices": 1, "with_note": 1, "days": export.FOCUS_DAYS}, man.get("focus")
dev = focus["devices"][0]
assert "10.0.0.20" in dev["note"] and "turns off at 3 am" in dev["note"], dev["note"]            # the note is read, with the address masked
assert len(dev["history"]["presence"]) == 2 and len(dev["history"]["mac_changes"]) == 1 and dev["card"]["brand"] == "Apple"
for leak in ("192.168.77.", "f0:18:98:aa", "3c:22:fb", "Giulia", "giulia", "Rossi", "rossi"):
    assert leak not in text, leak
assert "salotto" not in text and '"d2"' not in text and "TV-1" not in text                     # the other device is not in the section

# nothing flagged: no section
devices_config.set_override("d1", "focus", None)
devices_config.set_override("d1", "focus_note", None)
with zipfile.ZipFile(io.BytesIO(export.build_zip())) as z:
    assert "state/focus.json" not in z.namelist() and json.loads(z.read("manifest.json"))["focus"]["devices"] == 0
state.devices.clear()
print("TUTTO OK")
