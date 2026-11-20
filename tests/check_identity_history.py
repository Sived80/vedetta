"""The history of what Vedetta called a card (identity_changes.py, storage/history_identity.py): a name or a brand that appears or
changes is remembered with its source; a value that goes away is not a change; the first record after a start has nothing before
it; the rows go with a merged card, the purge of a network and the 90 days of retention; the route answers newest first.
    python tests/check_identity_history.py"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import identity_changes as ic  # noqa: E402
from app.storage.history import History  # noqa: E402

a = {"id": "d1", "name": "android-7f3a", "brand": None, "auto_name": True}
b = {"id": "d1", "name": "Pixel di Anna", "brand": "Google", "brand_source": "mdns", "auto_name": True}
rows = ic.between(a, b, 100)
assert [(r["field"], r["old"], r["new"], r["source"]) for r in rows] == [("name", "android-7f3a", "Pixel di Anna", "auto"), ("brand", None, "Google", "mdns")], rows
assert ic.between(None, b, 100) == []                                     # first record after a start
assert ic.between(b, {**b, "brand": None, "name": None}, 100) == []       # a value that goes away is no change
assert ic.between(b, dict(b), 100) == []
assert ic.between(a, {**a, "name": "x", "name_generated": True}, 1)[0]["source"] == "generated"

h = History(Path(tempfile.mkdtemp()) / "h.db")
h.identity_record(rows)
h.identity_record(ic.between(b, {**b, "name": "Telefono Anna"}, 200))
got = h.identity_changes("d1")
assert [(g["field"], g["new"]) for g in got] == [("name", "Telefono Anna"), ("brand", "Google"), ("name", "Pixel di Anna")], got
h.reassign_device("d1", "d9")
assert h.identity_changes("d1") == [] and len(h.identity_changes("d9")) == 3
h.prune_identity(200 + 91 * 86400)
assert h.identity_changes("d9") == []

from fastapi.testclient import TestClient  # noqa: E402
from app import main  # noqa: E402
from app.state import state  # noqa: E402
state.devices["nas"] = {"id": "nas", "ip": "10.0.0.5", "online": True}
client = TestClient(main.app)
assert client.get("/api/ha/identity/nas").json() == {"changes": []}
assert client.get("/api/ha/identity/ghost").status_code == 404
print("check_identity_history: ok")
