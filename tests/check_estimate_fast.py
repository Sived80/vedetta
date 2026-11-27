# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The size estimate of an export (export_estimate.estimate) on a big history: the same numbers as counting row by row, counted by
the database (a debug copy with days of ping samples took more than the 25 s the page waits, so the encrypted export stayed off);
several requests at the same time compute it once, the others take that result.
    python tests/check_estimate_fast.py"""
import os
import random
import sqlite3
import sys
import tempfile
import threading
import time

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import paths  # noqa: E402
from app.export import export_estimate as ee  # noqa: E402

db = paths.DATA_DIR / "big.db"
con = sqlite3.connect(db)
con.execute("CREATE TABLE presence_events (id INTEGER PRIMARY KEY, device_id TEXT, online INTEGER, ts REAL)")
con.execute("CREATE TABLE latency (device_id TEXT, ms REAL, ts REAL)")
con.execute("CREATE TABLE mac_takeover (ts REAL)")
con.execute("CREATE TABLE scans (ts REAL, result_json TEXT)")
mid = ee.day_start(0)
rnd = random.Random(7)
span = (mid - 95 * 86400, mid + 2 * 86400)                       # some rows too old, some in the future: neither counted
con.executemany("INSERT INTO latency VALUES ('d', 1.0, ?)", ((rnd.uniform(*span),) for _ in range(400_000)))
con.executemany("INSERT INTO presence_events (device_id, online, ts) VALUES ('d', 1, ?)", ((rnd.uniform(*span),) for _ in range(20_000)))
con.executemany("INSERT INTO mac_takeover VALUES (?)", ((rnd.uniform(*span),) for _ in range(500)))
con.executemany("INSERT INTO scans VALUES (?, ?)", ((rnd.uniform(*span), "x" * rnd.randint(0, 900)) for _ in range(3_000)))
con.execute("INSERT INTO scans VALUES (?, NULL)", (mid + 10,))
con.commit()
con.close()


def by_rows() -> list[int]:
    """The old way: every row read and counted at its day."""
    daily = [0] * ee.HORIZON_DAYS

    def add(ts, n):
        age = int((mid + 86400 - ts) // 86400)
        if 0 <= age < ee.HORIZON_DAYS:
            daily[age] += n
    c = sqlite3.connect(db)
    for table, size in (("presence_events", 90), ("latency", 40), ("mac_takeover", 250)):
        for (ts,) in c.execute(f"SELECT ts FROM {table}"):  # noqa: S608
            add(ts, size)
    for ts, n in c.execute("SELECT ts, length(result_json) FROM scans"):
        add(ts, int(n or 0) + 40)
    c.close()
    return daily


daily = [0] * ee.HORIZON_DAYS


def add(ts, n):
    age = int((mid + 86400 - ts) // 86400)
    if 0 <= age < ee.HORIZON_DAYS:
        daily[age] += n


t0 = time.perf_counter()
ee._add_database_row_sizes(db, add, mid)
took = time.perf_counter() - t0
assert daily == by_rows(), [(i, a, b) for i, (a, b) in enumerate(zip(daily, by_rows())) if a != b][:5]
assert took < 1.5, f"{took:.2f} s for 420 000 rows"                       # row by row it was several seconds here, minutes on a small box

# several requests at once: one computation
calls = []
real = ee._add_database_row_sizes
ee._add_database_row_sizes = lambda *a: (calls.append(1), time.sleep(0.3), real(*a))[2]
results = []
threads = [threading.Thread(target=lambda: results.append(ee.estimate())) for _ in range(5)]
for t in threads:
    t.start()
for t in threads:
    t.join()
assert len(results) == 5 and all(r is results[0] for r in results), "the waiting requests take the same result"
assert len(calls) == 1, f"computed {len(calls)} times"
print(f"check_estimate_fast: ok ({took:.2f} s)")
