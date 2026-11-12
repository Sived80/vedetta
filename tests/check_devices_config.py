"""Reference test of the device list file (storage/devices_config.py): ids and duplicates when adding, the IP move used when a device changes
address (refused if the new address is taken, the name follows when it was the address), automatic names that never override a user's choice,
the last deep scan, manual overrides, removal, and a failed write that leaves the previous file untouched."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.storage import devices_config as dc  # noqa: E402

tmp = Path(tempfile.mkdtemp())
dc.CONFIG_DIR = tmp
dc.DEVICES_PATH = tmp / "devices.yaml"

# nothing on disk: nothing happens, nothing fails
assert dc.load_devices() == [] and dc.update_ip("x", "10.0.0.9") is None and dc.remove_device("x") is False
assert dc.update_auto_name("x", "n", "mdns") is False and dc.update_scan_info("x", {}) is None and dc.set_override("x", "brand_user", "A") is None

added = dc.add_devices([{"ip": "10.0.0.1", "name": "Router", "port": 8080, "scan_info": {"k": "v"}, "name_source": "user"},
                        {"ip": "10.0.0.2"}, {"ip": "10.0.0.1"}, {"ip": "10.0.0.3", "id": "scan-10-0-0-2"}])
assert [d["ip"] for d in added] == ["10.0.0.1", "10.0.0.2", "10.0.0.3"], "an address already there is not added again"
assert [d["id"] for d in added] == ["scan-10-0-0-1", "scan-10-0-0-2", "scan-10-0-0-2-2"], "a clashing id gets a suffix"
r, b, c = added
assert r["port"] == 8080 and r["name"] == "Router" and r["scan_info"] == {"k": "v"} and r["name_source"] == "user"
assert b["port"] == 80 and b["adapter"] == "generic" and "name" not in b

# the IP move
assert dc.update_ip(r["id"], "10.0.0.2") is None, "the new address already belongs to another device"
assert dc.update_ip("nope", "10.0.0.50") is None
assert dc.update_ip(r["id"], "10.0.0.50") == "10.0.0.1"
assert [d["ip"] for d in dc.load_devices()][0] == "10.0.0.50" and dc.load_devices()[0]["name"] == "Router"
dc.update_device(b["id"], "10.0.0.2")                            # a name that is the address itself follows the address
assert dc.update_ip(b["id"], "10.0.0.60") == "10.0.0.2" and [d for d in dc.load_devices() if d["id"] == b["id"]][0]["name"] == "10.0.0.60"

# automatic names: a user's name is never replaced; a better source wins; the same name is not a change
assert dc.update_auto_name(r["id"], "Phone", "mdns") is False, "the user named it"
assert dc.update_auto_name(r["id"], "Phone", "mdns", force=True) is False, "not even when forced"
assert dc.update_auto_name(c["id"], "iPhone-1", "dhcp") is True
d = [x for x in dc.load_devices() if x["id"] == c["id"]][0]
assert d["name"] == "iPhone-1" and d["name_source"] == "dhcp"
assert dc.update_auto_name(c["id"], "iPhone-1", "dhcp") is False, "same name"
assert dc.update_auto_name(c["id"], "iPhone-2", "dhcp", force=True) is True and dc.update_auto_name("nope", "x", "dhcp") is False

# deep scan results and overrides
assert dc.update_scan_info(c["id"], {"http_title": "T"})["scan_info"] == {"http_title": "T"}
assert "scan_info" not in dc.update_scan_info(c["id"], {}), "an empty result clears it"
assert dc.update_scan_info("nope", {"a": 1}) is None
assert dc.set_override(c["id"], "brand_user", "Acme")["brand_user"] == "Acme"
assert "brand_user" not in dc.set_override(c["id"], "brand_user", None)
assert dc.set_override(c["id"], "not_a_field", "x") is None and dc.set_override("nope", "brand_user", "x") is None

# removal
assert dc.remove_device(c["id"]) is True and dc.remove_device(c["id"]) is False and len(dc.load_devices()) == 2

# the moves of one cycle in one write (1.0 step P5): every change applied at once, the addresses unique at the END (an exchange is a permutation),
# the name follows when it was the address; refused as a whole when a card is gone, its address changed meanwhile, or an address would be twice
d3 = dc.add_devices([{"ip": "10.0.5.1", "name": "10.0.5.1"}, {"ip": "10.0.5.2", "name": "Printer"}, {"ip": "10.0.5.3"}])
a3, b3, c3 = (x["id"] for x in d3)
ip_of = lambda: {d["id"]: (d["ip"], d.get("name")) for d in dc.load_devices() if d["id"] in (a3, b3, c3)}  # noqa: E731
assert dc.set_ips({a3: ("10.0.5.1", "10.0.5.2"), b3: ("10.0.5.2", "10.0.5.1")}) == {a3: "10.0.5.1", b3: "10.0.5.2"}
assert ip_of() == {a3: ("10.0.5.2", "10.0.5.2"), b3: ("10.0.5.1", "Printer"), c3: ("10.0.5.3", None)}, ip_of()
assert dc.set_ips({a3: ("10.0.5.2", "10.0.5.3"), c3: ("10.0.5.3", "10.0.5.9")}) == {a3: "10.0.5.2", c3: "10.0.5.3"}      # a chain
before = dc.DEVICES_PATH.read_text(encoding="utf-8")
assert dc.set_ips({a3: ("10.0.5.3", "10.0.5.1")}) is None, "the address of another card that stays: refused"
assert dc.set_ips({a3: ("10.0.5.2", "10.0.5.8")}) is None, "the card's address changed meanwhile: refused"
assert dc.set_ips({"nope": ("10.0.5.3", "10.0.5.8")}) is None and dc.set_ips({}) is None
assert dc.DEVICES_PATH.read_text(encoding="utf-8") == before, "a refused plan writes nothing"
writes = []
real_save = dc._save
dc._save = lambda data: (writes.append(1), real_save(data))
assert dc.set_ips({a3: ("10.0.5.3", "10.0.5.4"), b3: ("10.0.5.1", "10.0.5.5"), c3: ("10.0.5.9", "10.0.5.6")})
dc._save = real_save
assert writes == [1], "one write for all the moves of the cycle"
assert not hasattr(dc, "swap_ips"), "the exchange of two addresses is a plan of set_ips"

# a failed write leaves the file as it was (atomic write) and no temporary file behind
before = dc.DEVICES_PATH.read_text(encoding="utf-8")
real_replace = os.replace


def boom(*a, **k):
    raise OSError("disk full")


os.replace = boom
try:
    dc.update_device(r["id"], "Broken")
    raise AssertionError("the error must reach the caller")
except OSError:
    pass
finally:
    os.replace = real_replace
assert dc.DEVICES_PATH.read_text(encoding="utf-8") == before and not list(tmp.glob(".devices-*.tmp"))
print("TUTTO OK")
