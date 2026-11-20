"""1.0 step P11: the table routed_seen (storage/history_routed.py), the inventory by address of the networks behind the router.
- one row per (network, address): a second write of the same address updates it (last sight, MAC, name, status), never a second row;
- a MAC and a name may be missing (NULL): a row is never given a MAC it did not have;
- routed_rows reads the rows of one network (or all), routed_new the "new" ones seen since a time, routed_macs the status of each MAC written;
- one writer: no module of the app but history_routed.py inserts or updates routed_seen (the purge of a network only deletes).
Temporary data folder, invented private addresses.
    python tests/check_routed_store.py"""
import os
import re
import sys
import tempfile
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.storage.history import History  # noqa: E402

h = History(Path(tempfile.mkdtemp()) / "test.db")


def row(net, ip, first, last, mac=None, host=None, status="known"):
    return {"network": net, "ip": ip, "first_seen": first, "last_seen": last, "mac": mac, "host": host, "status": status}


h.routed_write([row("vlan60", "192.168.60.5", 1.0, 1.0), row("vlan60", "192.168.60.6", 1.0, 1.0, "02:00:5E:60:00:06", "printer"),
                row("vlan70", "192.168.70.5", 1.0, 1.0, status="new")])
assert len(h.routed_rows()) == 3 and len(h.routed_rows("vlan60")) == 2 and h.routed_rows("nope") == [], h.routed_rows()
h.routed_write([row("vlan60", "192.168.60.5", 1.0, 9.0, None, "speaker", "new")])
rows = {r["ip"]: r for r in h.routed_rows("vlan60")}
assert len(rows) == 2 and rows["192.168.60.5"] == row("vlan60", "192.168.60.5", 1.0, 9.0, None, "speaker", "new"), rows
assert rows["192.168.60.6"]["mac"] == "02:00:5E:60:00:06" and rows["192.168.60.6"]["host"] == "printer", rows
assert [r["ip"] for r in h.routed_new(5.0)] == ["192.168.60.5"], "only the new ones seen since the time"
assert sorted(r["ip"] for r in h.routed_new(0.0)) == ["192.168.60.5", "192.168.70.5"]
assert h.routed_macs() == {"02:00:5E:60:00:06": "known"}, h.routed_macs()
h.routed_write([])                       # nothing to write: nothing happens

# one writer
app = Path(__file__).resolve().parent.parent / "vedetta" / "app"
writers = [p.name for p in app.rglob("*.py") if re.search(r"(INSERT\s+(OR\s+\w+\s+)?INTO|UPDATE)\s+routed_seen", p.read_text(encoding="utf-8"), re.I)]
assert writers == ["history_routed.py"], writers
print("check_routed_store: ok")
