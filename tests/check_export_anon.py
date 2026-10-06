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
# a date is safe, any other 192.168.* / 172.16-31.* written with dashes is masked too (the safety check looks for exactly these)
assert a.text("date 2026-10-06 10-06-12-30 and 192-168-77-1 and 172_20_3_4") == "date 2026-10-06 10-06-12-30 and 10-2-0-1 and 10_3_0_4"
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


# --- emails, passwords and tokens in free text and in JSON fields
b = anonymize.Anonymizer()
masked = b.text("owner Dev.Name@Gmail.com and dev.name@gmail.com, other x@y.it; password=Hunter22 token: abc123xyz Authorization: Bearer abcdef12 mqtt://usr:pw99@10.1.1.1:1883")
assert "gmail" not in masked.lower() and "hunter22" not in masked.lower() and "abc123xyz" not in masked and "abcdef12" not in masked and "pw99" not in masked, masked
assert masked.count("email-1@masked.invalid") == 2 and "email-2@masked.invalid" in masked          # same address, same placeholder
assert b.data({"mqtt_password": "zzzzzz", "api_token": "tttttt", "mqtt_user": "someone", "name_by_user": True, "ok": "fine"}) ==     {"mqtt_password": "***", "api_token": "***", "mqtt_user": "***", "name_by_user": True, "ok": "fine"}
# the safety net: what is left readable is found, and a clean text is not flagged
c = anonymize.Anonymizer(); c.add_ip("192.168.7.5"); c.add_mac("f0:18:98:aa:bb:cc"); c.add_device(["Anna's iPhone"], "phone"); c.add_public_ip("93.184.216.34")
assert set(c.leaks("ip 192.168.7.5, id scan-192-168-7-5, F0-18-98-AA-BB-CC, Anna's iPhone, 93.184.216.34, a@b.it, token=abcdefgh")) ==     {"home network address", "MAC address", "name", "public address", "email address", "password or token"}
assert c.leaks("id deadf018 98aabbccdeadbeef and ab:f0:18:98:aa:bb:cc:dd") == []                  # part of a longer run of hex digits
assert c.leaks("mac f0:18:98:aa:bb:cc") == ["MAC address"] and c.leaks("f01898aabbcc!") == ["MAC address"]
assert c.leaks(c.text("ip 192.168.7.5, id scan-192-168-7-5, F0-18-98-AA-BB-CC, Anna's iPhone, 93.184.216.34, a@b.it, token=abcdefgh")) == []
assert c.leaks_data({"brand": "Anna's iPhone", "ssh_hostkey": "192.168.7.5"}) == []                   # fields kept on purpose are not judged
# a file the masking cannot clean is never delivered as it is: a log loses only the lines, a JSON that would break is given up
Broken = type("Broken", (anonymize.Anonymizer,), {"text": lambda self, s: s})
bk = Broken()
assert export._anonymize_text("data/x.log", "host 192.168.7.5", bk) == "[line removed: home network address]"
try:
    export._anonymize_text("data/x.json", chr(10).join(['{"a": 1,', ' "b": "192.168.7.5"}']), bk)
    raise AssertionError("a leaking file was accepted")
except export.MaskingFailed:
    pass

# --- any public address is masked, also one never announced (a hop, an address in an old log line)
d = anonymize.Anonymizer()
d.add_ip("192.168.50.10")
assert d.text("IP pubblico 128.116.154.247, salti 192.168.50.10 > 81.174.0.21 > 188.114.100.19 > 1.1.1.1 dns 8.8.8.8") == \
    "IP pubblico 203.0.113.1, salti 10.0.0.10 > 203.0.113.2 > 203.0.113.3 > 1.1.1.1 dns 8.8.8.8"
assert d.text("firmware 2.4.1.7 version: 3.1.0.9 and v1.2.3.4") == "firmware 2.4.1.7 version: 3.1.0.9 and v1.2.3.4"
assert d.text("128.116.154.247 again") == "203.0.113.1 again" and "128.116" not in str(d.mapping()["public_ips"].keys())
assert d.leaks("seen 81.174.0.21") == ["public address"] and d.leaks("dns 1.1.1.1 and 203.0.113.5") == []
big = anonymize.Anonymizer()
assert big.text("x 11.0.0.1 y") == "x 203.0.113.1 y" and big._public_ip("12.0.0.1") == "203.0.113.2"
for i in range(300):
    big._public_ip(f"20.0.{i // 250}.{i % 250 + 1}")
assert max(big._pub.values()) > 254 and big._public_ip("20.0.0.1").startswith("203.0.113.")
assert len({big._public_ip(ip) for ip in big._pub}) == len(big._pub)     # still one placeholder per address, past 254

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
# --- a line the masking cannot clean is replaced by a note, the rest of the file is kept
NL = chr(10)


class Lazy(anonymize.Anonymizer):
    def text(self, s):
        return NL.join(l if "SKIPME" in l else super(Lazy, self).text(l) for l in s.split(NL))


lz = Lazy()
lz.add_ip("192.168.5.5")
report = []
out = export._anonymize_text("data/x.log", NL.join(["ok 192.168.5.5", "SKIPME 192.168.5.5", "fine"]), lz, report)
assert out.split(NL) == ["ok 10.0.0.5", "[line removed: home network address]", "fine"], out
assert report == [{"file": "data/x.log", "lines_removed": 1, "problem": "home network address"}], report
assert export._anonymize_text("data/y.log", "all 192.168.5.5 fine", lz, report) == "all 10.0.0.5 fine" and len(report) == 1

# --- the export keeps going when one file cannot be masked: that file is left out, the manifest says which and why
orig_text = export._anonymize_text
def refuse_log(name, text, anon_, report=None):
    if name.endswith("app.log"):
        raise export.MaskingFailed(f"{name}: name")
    return orig_text(name, text, anon_, report)
export._anonymize_text = refuse_log
try:
    with zipfile.ZipFile(io.BytesIO(export.build_zip())) as z:
        assert "data/app.log" not in z.namelist() and "data/settings.json" in z.namelist() and "state/devices_compact.json" in z.namelist()
        man = json.loads(z.read("manifest.json"))
    assert man["omitted"] == [{"file": "data/app.log", "problem": "name"}], man["omitted"]       # the kind, never the value
    assert export.last_omitted == man["omitted"]
finally:
    export._anonymize_text = orig_text
with zipfile.ZipFile(io.BytesIO(export.build_zip())) as z:
    assert "data/app.log" in z.namelist() and json.loads(z.read("manifest.json"))["omitted"] == [] and export.last_omitted == []
state.devices.clear()
print("TUTTO OK")
