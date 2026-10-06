"""Export for analysis: IPs, MACs and names are anonymised only inside the zip, the same value always gets the
same placeholder, the live data does not change and no original value is left in the file."""
import io
import json
import os
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import anonymize, dhcp, export, ha_registry, mdns_listener, paths  # noqa: E402
from app.state import state  # noqa: E402

# --- the pieces
a = anonymize.Anonymizer()
for ip in ("192.168.50.10", "192.168.50.23", "10.9.8.7"):
    a.add_ip(ip)
a.add_mac("F0:18:98:AA:BB:CC")
a.add_mac("3c:22:fb:11:22:33")
a.add_public_ip("93.184.216.34")
a.add_area("Camera di Anna")
assert a.add_device(["Anna's iPhone", "annas-iphone", "Annas iPhone"], "phone") == "iPhone-1"
assert a.add_device(["Marco iPhone"], "phone") == "iPhone-2"
assert a.add_device(["Samsung TV salotto"], "media") == "TV-1"
assert a.add_device(["boh-4567"], "iot") == "IoT-1"                      # no product word: the type decides
assert a.add_device(["Shelly"], None) is None                             # a bare brand name is kept (the debug needs it)
assert a.add_device(["pve"], None) is None and a.text("pve-api") == "pve-api"      # three letters: technical, kept
assert a.add_device(["ab"], None) is None and a.add_device(["12345"], None) is None

out = a.text("host 192.168.50.10 and 192.168.50.23, other net 10.9.8.7, gateway 127.0.0.1, firmware 2.4.1.0.5, public 93.184.216.34")
assert out == "host 10.0.0.10 and 10.0.0.23, other net 10.1.0.7, gateway 127.0.0.1, firmware 2.4.1.0.5, public 203.0.113.1", out
# the same address in a device id ("scan-192-168-50-10"): only for networks that exist here, so dates and versions are safe
assert a.text("id scan-192-168-50-10, scan_192_168_50_23, net 10-9-8-7") == "id scan-10-0-0-10, scan_10_0_0_23, net 10-1-0-7"
assert a.text("date 2026-10-06 10-06-12-30 and 192-168-77-1") == "date 2026-10-06 10-06-12-30 and 192-168-77-1"
assert a.text("mac f0:18:98:aa:bb:cc / F0-18-98-AA-BB-CC / 3C:22:FB:11:22:33") == \
    "mac f0:18:98:00:00:01 / F0-18-98-00-00-01 / 3C:22:FB:00:00:02"      # prefix kept, case and separator kept
assert a.text("flat f018 98aabbcc? f01898aabbcc tail aabbcc") == "flat f018 98aabbcc? f01898000001 tail 000001"
assert a.text("Anna's iPhone / annas-iphone / ANNAS_IPHONE / Marco iPhone") == "iPhone-1 / iPhone-1 / iPhone-1 / iPhone-2"
assert a.text("Samsung TV salotto is in Camera di Anna") == "TV-1 is in Area-1"
assert a.text("iPhone of someone else") == "iPhone of someone else"       # only names of this network are replaced
assert a.text("") == "" and a.text("Shelly 1PM") == "Shelly 1PM"
m = a.mapping()
assert m["macs"]["f0:18:98:00:00:01"] == "f0:18:98:aa:bb:cc" and m["public_ips"]["203.0.113.1"] == "93.184.216.34"
assert "annas-iphone" in m["names"]["iPhone-1"] and m["ip_networks"]["10.0.0.x"] == "192.168.50.x"

# --- the whole zip, on a fake network
tmp = Path(tempfile.mkdtemp())
paths.DATA_DIR = tmp
export.paths.DATA_DIR = tmp
secret_names = ["Giulia's iPad", "giulia-ipad", "Cucina Rossi", "salotto-tv-rossi"]
state.devices.clear()
state.devices["d1"] = {"id": "d1", "ip": "192.168.77.20", "mac": "f0:18:98:aa:bb:cc", "name": "Giulia's iPad", "brand": "Apple",
                       "extra": {}, "scanned_ports": [], "online": True}
state.devices["d2"] = {"id": "d2", "ip": "192.168.77.31", "mac": "3c:22:fb:11:22:33", "name": "salotto-tv-rossi", "brand": "Samsung",
                       "extra": {}, "scanned_ports": [], "online": False}
dhcp.seen.clear()
dhcp.seen["f0:18:98:aa:bb:cc"] = {"hostname": "giulia-ipad", "vendor_class": "", "seen": 1}
mdns_listener.by_mac.clear(); mdns_listener.by_ip.clear()
ha_registry._state["by_mac"] = {"3c:22:fb:11:22:33": {"name": "salotto-tv-rossi", "area": "Cucina Rossi", "manufacturer": "Samsung"}}
ha_registry._state["by_ip"] = {}
(tmp / "settings.json").write_text(json.dumps({"mqtt_password": "hunter2", "note": "Cucina Rossi 192.168.77.20"}), encoding="utf-8")
(tmp / "app.log").write_text("probe 192.168.77.31 (salotto-tv-rossi) mac 3C:22:FB:11:22:33 owner Giulia's iPad\n", encoding="utf-8")
db = sqlite3.connect(tmp / "vedetta.db")
db.execute("CREATE TABLE seen (ip TEXT, mac TEXT, name TEXT, ms REAL)")
db.execute("INSERT INTO seen VALUES ('192.168.77.20', 'f0:18:98:aa:bb:cc', 'Giulia''s iPad', 4.5)")
db.commit(); db.close()

before = json.dumps(state.devices, sort_keys=True)
blob = export.build_zip()
assert json.dumps(state.devices, sort_keys=True) == before, "the live data must not change"

with zipfile.ZipFile(io.BytesIO(blob)) as z:
    names = z.namelist()
    assert not any("mapping" in n for n in names), names                   # the key to decode stays at home
    files = {n: z.read(n) for n in names}
    dbfile = tmp / "out.db"
    dbfile.write_bytes(files["data/vedetta.db"])
rows = sqlite3.connect(dbfile).execute("SELECT ip, mac, name, ms FROM seen").fetchall()
assert rows == [("10.0.0.20", "f0:18:98:00:00:01", "iPad-1", 4.5)], rows
for n, raw in files.items():
    if n == "data/vedetta.db":
        continue
    text = raw.decode("utf-8")
    for leak in ("192.168.77.", "f0:18:98:aa", "3c:22:fb:11", "3C:22:FB:11", "Giulia", "giulia", "Rossi", "rossi", "hunter2"):
        assert leak not in text, (n, leak)
assert b"10.0.0.31" in files["data/app.log"] and b"TV-1" in files["data/app.log"] and b"f0:18:98:00:00:01" in files["state/devices_compact.json"]
assert b'"***"' in files["data/settings.json"]
mapping = json.loads((tmp / export.MAPPING_FILE).read_text(encoding="utf-8"))      # for the owner, outside the zip
assert mapping["names"]["iPad-1"] and mapping["macs"]["f0:18:98:00:00:01"] == "f0:18:98:aa:bb:cc"
# the second export does not take the mapping file for data
with zipfile.ZipFile(io.BytesIO(export.build_zip())) as z:
    assert not any("export_mapping" in n for n in z.namelist())
state.devices.clear()
print("TUTTO OK")
