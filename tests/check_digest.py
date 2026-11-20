"""The summary of a window (analysis/digest.py): new, back after a long absence, gone silent, and only the changes of the window: a
device off for weeks is not said again every night; phones and cards Vedetta does not watch are never silent; the first window of an
installation claims nothing. History.returns_after finds the returns; the route answers.
    python tests/check_digest.py"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.analysis import digest as dg  # noqa: E402
from app.storage.history import History  # noqa: E402

H, D = 3600, 86400
END = 100 * D
START = END - 12 * H

cards = {
    "new": {"first_seen": END - 2 * H, "online": True, "last_seen": END},
    "old_off": {"first_seen": 1, "online": False, "last_seen": END - 20 * D},            # off for weeks: already said, not again
    "crossed": {"first_seen": 1, "online": False, "last_seen": END - 30 * H},            # 24 h passed during this window
    "too_soon": {"first_seen": 1, "online": False, "last_seen": END - 3 * H},             # off 3 h: not silent yet
    "phone": {"first_seen": 1, "online": False, "last_seen": END - 30 * H, "is_mobile": True},
    "paused": {"first_seen": 1, "online": False, "last_seen": END - 30 * H, "watched": False},
    "nas": {"first_seen": 1, "online": True, "last_seen": END},
}
returns = [("nas", END - 5 * H, 40 * D), ("phone", END - H, 3 * H), ("nas", START - H, 30 * D), ("ghost", END - H, 9 * D)]
r = dg.digest(cards, returns, START, END, installed_at=1)
assert r["new"] == ["new"], r["new"]
assert r["back"] == [{"id": "nas", "at": END - 5 * H, "away_s": 40 * D}], r["back"]          # the phone asleep 3 h is no return
assert r["silent"] == ["crossed"], r["silent"]
assert r["cards"] == 7 and r["online"] == 2 and r["first_window"] is False
first = dg.digest(cards, returns, START, END, installed_at=END - H)
assert first["first_window"] and first["new"] == first["back"] == first["silent"] == []

# returns_after on the database
h = History(Path(tempfile.mkdtemp()) / "h.db")
h.record_presence("nas", None, None, True, 0)
h.record_presence("nas", None, None, False, 10)
h.record_presence("nas", None, None, True, 10 + 2 * D)
h.record_presence("tv", None, None, False, 100)
h.record_presence("tv", None, None, True, 200)
assert h.returns_after(0, 10 * D, D) == [("nas", 10 + 2 * D, 2 * D)], h.returns_after(0, 10 * D, D)
assert h.returns_after(0, 10 * D, 50) == [("tv", 200, 100), ("nas", 10 + 2 * D, 2 * D)]

from fastapi.testclient import TestClient  # noqa: E402
from app import main  # noqa: E402
from app.state import state  # noqa: E402
state.devices["nas"] = {"id": "nas", "ip": "10.0.0.5", "online": True}
body = TestClient(main.app).get("/api/ha/digest?hours=12").json()
assert {"new", "back", "silent", "cards", "online", "labels", "first_window"} <= set(body), body
print("check_digest: ok")
