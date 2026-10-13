"""Golden-master test of PresenceMixin.presence_segments (online/offline segments of a device in a window, from the presence_events table of an in-memory History): 3000 generated
situations - no events, events before, inside and exactly on the edges of the window (ties on the same instant are ordered by id), repeated states, a window that is empty or reversed,
integer and float window edges, another device with events in the same table - must give exactly the returned dictionary (key order included) stored in tests/golden/presence_segments.json,
written from the code as it was before the method was split (digest per case plus a readable sample).
Regenerate only on purpose:  PRESENCE_SEG_GOLDEN_UPDATE=1 python tests/check_presence_segments_golden.py"""
import hashlib
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.storage.history import History  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "presence_segments.json"
N = 3000
rng = random.Random(1357)


def pick(seq):
    return seq[rng.randrange(len(seq))]


def run_case():
    h = History(Path(":memory:"))
    since = pick([0, 100, 100.5, 250, 7])
    until = since + pick([0, 1, 50, 150, 300, 150, 300, 200, -20, 0.5])
    n = rng.randrange(0, 12)
    stamps = [since, until, since - 1, until + 1, since + 0.25] + [since + rng.randrange(-40, 400) / pick([1, 1, 2, 4]) for _ in range(8)]
    with h._lock:
        for _ in range(n):
            dev = "dev1" if rng.random() < 0.8 else "dev2"
            h._db.execute("INSERT INTO presence_events (device_id, online, ts) VALUES (?, ?, ?)", (dev, pick([0, 1, 1, 0, 2]), pick(stamps)))
        h._db.commit()
    try:
        out = h.presence_segments("dev1", since, until)
        res = json.loads(json.dumps(out))
        res = [res, [type(out["from"]).__name__, type(out["to"]).__name__]]
    except Exception as exc:
        res = {"exception": type(exc).__name__}
    h._db.close()
    return res


cases = [run_case() for _ in range(N)]
digests = [hashlib.sha1(json.dumps(c).encode()).hexdigest()[:12] for c in cases]
out = json.loads(json.dumps({"digests": digests, "sample": cases[:30]}))
if os.environ.get("PRESENCE_SEG_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(out, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want["digests"]) == len(digests) == N
for i, (x, y) in enumerate(zip(digests, want["digests"])):
    assert x == y, "case %d differs: %s" % (i, json.dumps(cases[i])[:700])
assert out["sample"] == want["sample"]
assert not any(isinstance(c, dict) for c in cases)
segs = [c[0]["segments"] for c in cases]
assert sum(1 for s in segs if not s) > 200 and sum(1 for s in segs if len(s) >= 3) > 400, "scenarios too uniform"
assert sum(1 for s in segs if any(x["online"] for x in s)) > 1000 and sum(1 for s in segs if any(not x["online"] for x in s)) > 700
assert sum(1 for c in cases if c[0]["online_pct"] is None) > 300 and sum(1 for c in cases if c[0]["online_pct"] not in (None, 0.0, 100.0)) > 400
assert sum(1 for c in cases if c[0]["to"] < c[0]["from"]) > 100 and any(c[0]["to"] == c[0]["from"] for c in cases)
assert any(x["from"] == c[0]["from"] and x["to"] == c[0]["to"] for c in cases for x in c[0]["segments"])
assert any(c[1][0] == "int" for c in cases) and any(c[1][0] == "float" for c in cases)
print("TUTTO OK")
