"""Hiding findings (storage/health_hidden.py, POST /api/ha/health/hidden): two choices made almost together are both kept (apply reads, changes
and writes the file in a worker thread: without a lock the second write lost the first), and a list far longer than what is ever kept is
refused at once with a 400 (the search in a list made 20,000 ids take seconds of a worker thread, 100,000 minutes).
Found by the review of 1.0.1. Temporary data folder, invented ids.
    python tests/check_health_hidden_race.py"""
import os
import sys
import tempfile
import threading
import time

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.routes import ha  # noqa: E402
from app.storage import health_hidden as hh  # noqa: E402

# 1) two "hide" at the same time: both read the list before either writes it (when nothing serializes them)
real_load = hh.load
barrier = threading.Barrier(2, timeout=1)


def load_then_meet():
    out = real_load()
    try:
        barrier.wait()
    except threading.BrokenBarrierError:
        assert barrier.broken      # the other thread waits for the lock: the meeting cannot happen, and that is the point
    return out


hh.load = load_then_meet
threads = [threading.Thread(target=hh.apply, args=([finding_id], [])) for finding_id in ("rule1|aa", "rule2|bb")]
for t in threads:
    t.start()
for t in threads:
    t.join()
hh.load = real_load
hh._cache = None
assert sorted(hh.load()) == ["rule1|aa", "rule2|bb"], hh.load()

# 2) a list far too long: a quick 400, nothing changed
app = FastAPI()
app.include_router(ha.router)
client = TestClient(app, raise_server_exceptions=False)
start = time.monotonic()
r = client.post("/api/ha/health/hidden", json={"hide": ["id%d" % i for i in range(20000)], "show": []})
elapsed = time.monotonic() - start
assert r.status_code == 400 and r.json()["detail"] == "Invalid request", (r.status_code, r.text[:80])
assert elapsed < 2, elapsed
assert client.post("/api/ha/health/hidden", json={"show": ["x"] * (hh.MAX_HIDDEN + 1)}).status_code == 400
assert sorted(hh.load()) == ["rule1|aa", "rule2|bb"]

# 3) a list up to the limit is still taken, and quickly
r = client.post("/api/ha/health/hidden", json={"hide": ["id%d" % i for i in range(hh.MAX_HIDDEN)], "show": ["rule1|aa"]})
assert r.status_code == 200 and len(r.json()["hidden"]) == hh.MAX_HIDDEN and "rule1|aa" not in r.json()["hidden"], r.status_code
print("check_health_hidden_race: ok")
