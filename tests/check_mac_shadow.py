"""Shadow data per MAC: collected for analysis, never read to decide what a card shows. A card whose MAC changes leaves a
takeover row with what it carried over; an unchanged MAC is not written on every cycle; it ends in the anonymised export."""
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.export import mac_shadow, anonymize
from app.scan import dhcp  # noqa: E402
from app.storage.history import History  # noqa: E402

H = History(Path(tempfile.mkdtemp()) / "t.db")
mac_shadow.history = H
now = time.time()
A, B = "aa:bb:cc:00:00:01", "f4:cf:a2:00:00:02"
dhcp.seen[A] = {"hostname": "iPhone-di-Mario", "vendor_class": None}
dhcp.seen[B] = {"hostname": "shellyplug-ABC123", "vendor_class": None}


def run(job):
    if job:
        job()


card = lambda mac, name: {"id": "scan-10-0-0-9", "ip": "10.0.0.9", "mac": mac, "name": name, "brand": "Apple" if mac == A else "Shelly",
                          "extra": {}, "is_mobile": mac == A, "mobile_score": 7 if mac == A else 0}

# first sight of a MAC: one row, no takeover
run(mac_shadow.observe("scan-10-0-0-9", None, card(A, "Apple mobile"), None, now))
# the same MAC again right away: nothing is written
assert mac_shadow.observe("scan-10-0-0-9", card(A, "Apple mobile"), card(A, "Apple mobile"), A, now + 30) is None
# another MAC answers at the same address: takeover with what the card carried over
run(mac_shadow.observe("scan-10-0-0-9", card(A, "Apple mobile"), card(B, "Apple mobile"), A, now + 60))
with H._lock:
    mem = {r["mac"]: dict(r) for r in H._db.execute("SELECT * FROM mac_memory")}
    tk = [dict(r) for r in H._db.execute("SELECT * FROM mac_takeover")]
assert set(mem) == {A, B}, mem
assert mem[A]["dhcp_name"] == "iPhone-di-Mario" and mem[B]["dhcp_name"] == "shellyplug-ABC123"
assert len(tk) == 1 and tk[0]["old_mac"] == A and tk[0]["new_mac"] == B and tk[0]["new_known"] == 0, tk
assert tk[0]["carried_name"] == "Apple mobile" and tk[0]["carried_brand"] == "Apple"
# the first MAC comes back: known this time
run(mac_shadow.observe("scan-10-0-0-9", card(B, "Apple mobile"), card(A, "Apple mobile"), B, now + 120))
with H._lock:
    tk = [dict(r) for r in H._db.execute("SELECT new_known FROM mac_takeover ORDER BY id")]
assert [r["new_known"] for r in tk] == [0, 1], tk
# a card without a MAC never raises or writes
assert mac_shadow.observe("x", None, {"id": "x", "mac": None}, None, now) is None

# the export masks these tables like any other (the copy goes through the same replacement)
con = sqlite3.connect(":memory:")
con.executescript("CREATE TABLE t (a TEXT)")
anon = anonymize.Anonymizer()
masked = anon.text("old_mac aa:bb:cc:12:34:56 at 192.168.178.114")
assert "aa:bb:cc:12:34:56" not in masked and "192.168.178.114" not in masked, masked
print("TUTTO OK")
