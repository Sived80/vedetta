"""Golden-master test of MacLayerMixin.observe (writes a batch of (ip, mac, source, ts) observations into ip_mac, ip_mac_session and ip_flip in one transaction): 2500 generated
sequences of 1-4 batches on an in-memory History - repeated and unordered timestamps inside a batch, several sources (only "arp" makes flips), the same pair seen again after a gap
shorter, equal to or longer than the session gap (600 s), a MAC taking over an address, empty batches, generators instead of lists - must give exactly the returned counts AND the
final content of the three tables (in row order) stored in tests/golden/maclayer_observe.json, written from the code as it was before the method was split (digest per case plus a
readable sample).
Regenerate only on purpose:  MACLAYER_OBSERVE_GOLDEN_UPDATE=1 python tests/check_maclayer_observe_golden.py"""
import hashlib
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.maclayer import Observation  # noqa: E402
from app.storage.history import History  # noqa: E402
from app.storage.history_maclayer import SESSION_GAP_S  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "maclayer_observe.json"
N = 2500
rng = random.Random(97)
IPS = ["192.168.1.%d" % i for i in (1, 2, 3)]
MACS = ["AA:BB:CC:00:00:0%d" % i for i in (1, 2, 3)]
SOURCES = ["arp", "arp", "arp", "mdns", "ssdp"]


def pick(seq):
    return seq[rng.randrange(len(seq))]


def batch(base):
    out = []
    for _ in range(rng.randrange(0, 7)):
        ts = base + pick([0, 0, 1, 5, 100, SESSION_GAP_S - 1, SESSION_GAP_S, SESSION_GAP_S + 1, 5000, 0.5])
        out.append(Observation(pick(IPS), pick(MACS), pick(SOURCES), ts))
    return out


def dump(h):
    with h._lock:
        return [[list(r) for r in h._db.execute("SELECT * FROM %s ORDER BY rowid" % t).fetchall()] for t in ("ip_mac", "ip_mac_session", "ip_flip")]


def run_case():
    h = History(Path(":memory:"))
    counts = []
    base = 1_000_000
    for _ in range(rng.randrange(1, 5)):
        obs = batch(base)
        base += pick([0, 50, 300, 700, 2000, 10000, -100])
        try:
            counts.append(h.observe(iter(obs)) if rng.random() < 0.2 else h.observe(obs))
        except Exception as exc:
            counts.append("exception " + type(exc).__name__)
    res = [counts, dump(h), h._db.in_transaction]
    h._db.close()
    return res


cases = [run_case() for _ in range(N)]
digests = [hashlib.sha1(json.dumps(c).encode()).hexdigest()[:12] for c in cases]
out = json.loads(json.dumps({"digests": digests, "sample": cases[:12]}))
if os.environ.get("MACLAYER_OBSERVE_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(out, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want["digests"]) == len(digests) == N
for i, (x, y) in enumerate(zip(digests, want["digests"])):
    assert x == y, "case %d differs: %s" % (i, json.dumps(cases[i])[:900])
assert out["sample"] == want["sample"]
assert not any(isinstance(n, str) for c in cases for n in c[0])
assert sum(1 for c in cases if c[1][2]) > 300 and sum(1 for c in cases if len(c[1][2]) >= 2) > 80, "no flips"
assert sum(1 for c in cases if len(c[1][1]) > len(c[1][0])) > 20, "sessions never split"
assert sum(1 for c in cases if c[1][0] and any(r[5] >= 2 for r in c[1][0])) > 800 and any(n == 0 for c in cases for n in c[0]) and any(n >= 4 for c in cases for n in c[0])
assert not any(c[2] for c in cases)
assert any(r[4] > 0 for c in cases for r in c[1][2]) and any(r[4] == 0 for c in cases for r in c[1][2]), "gap values"
print("TUTTO OK")

