"""The export of a period keeps only that period in the copy of the database, the tables of 1.0 too: the name changes of the cards
(identity_change, by their time) and the addresses seen behind the router (routed_seen, those seen at some point of the period).
The real schema (History), a copy of the file, then the cut of export_estimate._period_db."""
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.export import export_estimate  # noqa: E402
from app.storage.history import history  # noqa: E402

DAY = 86400.0
history.identity_record([{"device_id": "d1", "ts": t, "field": "name", "old": "a", "new": "b", "source": "mdns"} for t in (1 * DAY, 5 * DAY, 9 * DAY)])
history.routed_write([{"network": "n1", "ip": f"10.9.0.{i}", "first_seen": first, "last_seen": last, "mac": None, "host": None, "status": "on"}
                      for i, (first, last) in enumerate(((0, 2 * DAY), (3 * DAY, 6 * DAY), (1 * DAY, 8 * DAY), (8 * DAY, 9 * DAY)), start=1)])
history._db.commit()
copy = Path(tempfile.mkdtemp()) / "vedetta.db"
with history._lock:
    dst = sqlite3.connect(copy)
    history._db.backup(dst)
    dst.close()

export_estimate._period_db(copy, 4 * DAY, 7 * DAY)
con = sqlite3.connect(copy)
assert [r[0] for r in con.execute("SELECT ts FROM identity_change ORDER BY ts")] == [5 * DAY]
assert [r[0] for r in con.execute("SELECT ip FROM routed_seen ORDER BY ip")] == ["10.9.0.2", "10.9.0.3"]     # seen during the period
con.close()
shutil.rmtree(copy.parent, ignore_errors=True)
print("ALL OK")
