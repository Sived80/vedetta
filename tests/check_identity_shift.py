"""Two different devices behind one card (ha/identity_shift.py): the judgement is rocky (two independent families of evidence, vetoes for private MACs,
shared MACs and network roles, "same" evidence wins) and it only reads: a name chosen by hand is never touched."""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import i18n  # noqa: E402
from app.ha import identity_shift as ids  # noqa: E402
from app.scan import dhcp, mdns_listener  # noqa: E402
from app.storage.history import History  # noqa: E402


def prof(mac, cls=None, grp=None, dname=None, mname=None, ha=None, private=False, ip="10.0.0.106"):
    return {"mac": mac, "ip": ip, "private": private, "dhcp_class": cls, "family": ids.family(cls), "dhcp_name": dname, "grp": grp, "mdns_name": mname,
            "ha": ha, "vendor": None, "first_seen": 0}


laptop = prof("8c:fd:f0:00:00:08", "chromeos", "pc")
ps5 = prof("50:b0:3b:00:00:2b", "PS5", "media")

# the real case: ChromeOS laptop and PS5 on the same address (two independent families: DHCP family and recognised group)
j = ids.judge(laptop, ps5, set())
assert j["verdict"] == "different" and j["reasons"] == ["dhcp_family", "group"], j
assert ids.family("PS5") == "console" and ids.family("chromeos") == "chromeos" and ids.family("android-dhcp-15") == "android"

# one family only is not enough
assert ids.judge(prof("a", "chromeos", "pc"), prof("b", "chromeos", "media"), set())["verdict"] == "unknown"
assert ids.judge(prof("a", "chromeos", None), prof("b", "PS5", None), set())["verdict"] == "unknown", "senza il gruppo basta una sola famiglia: no"
# no data: nothing
assert ids.judge(prof("a"), prof("b"), set())["verdict"] == "unknown"

# vetoes: phones with a private (random) MAC, a MAC behind several cards (a repeater that clones it), a MAC with a network role
assert ids.judge(laptop, prof("12:d7:2c:00:00:1d", "android-dhcp-15", "phone", private=True), set())["vetoes"] == ["private"]
assert ids.judge(laptop, ps5, {ps5["mac"]})["verdict"] == "unknown" and ids.judge(laptop, ps5, {ps5["mac"]})["vetoes"] == ["shared"]
assert ids.judge(laptop, ps5, set(), role_b=True)["vetoes"] == ["role"]

# the same device with two network cards (Wi-Fi and dock): same DHCP name, or the same Bonjour name, or the same Home Assistant device: "same"
wifi = prof("aa:00:00:00:00:01", "MSFT 5.0", "pc", dname="studio-pc")
dock = prof("aa:00:00:00:00:02", "MSFT 5.0", "pc", dname="studio-pc")
assert ids.judge(wifi, dock, set())["verdict"] == "same"
assert ids.judge(prof("a", mname="salotto"), prof("b", mname="salotto", cls="PS5", grp="media"), set())["verdict"] == "same", "lo stesso nome Bonjour vince su ogni differenza"
ha = ("Acme", "TV-1", "Soggiorno")
assert ids.judge(prof("a", ha=ha, cls="PS5"), prof("b", ha=ha, grp="media"), set())["verdict"] == "same"
# a replacement of the same kind (same family, same group): nothing to say
assert ids.judge(prof("a", "udhcp 0.9", "iot"), prof("b", "udhcp 0.9", "iot"), set())["verdict"] == "unknown"

# the check on a card, with the memory per MAC in a database
tmp = Path(tempfile.mkdtemp())
H = History(tmp / "t.db")
ids.history = H
now = time.time()
H.mac_memory_set("8c:fd:f0:00:00:08", "scan-10-0-0-106", "10.0.0.106", {"name": "Laptop-1", "brand": "Acer", "grp": "pc", "dhcp_class": "chromeos"}, now - 3000)
H.mac_memory_set("50:b0:3b:00:00:2b", "scan-10-0-0-106", "10.0.0.106", {"name": "Laptop-1", "brand": "Acer", "grp": "media", "dhcp_class": "PS5"}, now - 1000)
dhcp.seen.clear(); mdns_listener.by_mac.clear()
dhcp.seen["50:b0:3b:00:00:2b"] = {"vendor_class": "PS5", "prl": "1,3,15,6"}
dhcp.seen["8c:fd:f0:00:00:08"] = {"vendor_class": "chromeos"}
ids.RESULTS.clear(); ids._checked.clear(); ids._alerted.clear()
last = {"scan-10-0-0-106": "50:b0:3b:00:00:2b", "scan-10-0-0-1": "30:de:4b:00:00:01"}
assert ids.due("scan-10-0-0-106", "50:b0:3b:00:00:2b", now)
f = ids.evaluate("scan-10-0-0-106", "50:B0:3B:00:00:2B", last, now)
assert f and f["verdict"] == "different" and f["new"] and f["a"]["mac"] == "8c:fd:f0:00:00:08" and f["b"]["mac"] == "50:b0:3b:00:00:2b", f
assert not ids.due("scan-10-0-0-106", "50:b0:3b:00:00:2b", now + 60), "non si rigiudica a ogni controllo"
assert ids.due("scan-10-0-0-106", "8c:fd:f0:00:00:08", now + 60), "ma subito se cambia il MAC"
assert ids.due("scan-10-0-0-106", "50:b0:3b:00:00:2b", now + ids.RECHECK_S + 1)
f2 = ids.evaluate("scan-10-0-0-106", "50:b0:3b:00:00:2b", last, now + 700)
assert f2 and not f2["new"], "l'avviso e' una volta sola per coppia"
for lang in ("it", "en"):
    i18n.use(lang)
    a = ids.attrs_for("scan-10-0-0-106", i18n.t)
    assert [x["key"] for x in a] == ["other_device", "other_device_why"] and "PS5" in a[0]["value"] and a[1]["value"], a
assert ids.attrs_for("scan-10-0-0-1", i18n.t) == []

# a repeater that clones its MAC: the same MAC behind three cards, nothing is said
H.mac_memory_set("1c:aa:00:00:00:99", "scan-10-0-0-50", "10.0.0.50", {"name": "TV", "grp": "media", "dhcp_class": "android-dhcp-11"}, now - 900)
H.mac_memory_set("1c:aa:00:00:00:98", "scan-10-0-0-50", "10.0.0.50", {"name": "TV", "grp": "pc", "dhcp_class": "chromeos"}, now - 100)
rep = {"scan-10-0-0-50": "1c:aa:00:00:00:98", "scan-10-0-0-51": "1c:aa:00:00:00:98", "scan-10-0-0-52": "1c:aa:00:00:00:98"}
assert ids.evaluate("scan-10-0-0-50", "1c:aa:00:00:00:98", rep, now) is None and "scan-10-0-0-50" not in ids.RESULTS
print("TUTTO OK")
