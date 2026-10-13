"""Golden-master test of blocklist.list_items (reads config/ignored.json with a cache keyed on the file modification time): 3000 generated situations - file missing, unreadable
JSON, not a list, lists with good and bad entries (unknown kind, empty or non-string value, padded value, missing/non-string id, long or non-string label), a cache that is still
valid (same stamp, even with a stamp of None) or stale - must give exactly the returned list (and whether it is the very cached object) AND the final content of the cache stored in
tests/golden/blocklist_list_items.json, written from the code as it was before the function was split (digest per case plus a readable sample).
Regenerate only on purpose:  BLOCKLIST_ITEMS_GOLDEN_UPDATE=1 python tests/check_blocklist_list_items_golden.py"""
import hashlib
import json
import os
import random
import sys
import tempfile
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()      # never the real folder of the developer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.storage import blocklist  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "blocklist_list_items.json"
N = 3000
rng = random.Random(4242)
blocklist.PATH = Path(tempfile.mkdtemp()) / "ignored.json"


def pick(seq):
    return seq[rng.randrange(len(seq))]


KINDS = ["mac", "ip", "name", "mac", "ip", "name", "other", "", None, 5, "MAC"] + ["mac", "ip", "name"] * 3
VALUES = ["aa:bb:cc:00:00:01", "  192.168.1.5  ", "Phone di Anna", "x", " ", "", "   ", None, 7, ["a"], "\tpad\n", "é" * 5]
IDS = ["abc12345", "", None, 12, "x" * 20]
LABELS = ["", "short", "L" * 200, "L" * 80, "L" * 81, None, 5, "ünï"]
ADDED = [None, 1700000000, "yesterday", 0, 1.5]


def entry():
    r = rng.random()
    if r < 0.08:
        return pick([None, 3, "str", [], [1]])
    it = {}
    for key, pool in (("id", IDS), ("kind", KINDS), ("value", VALUES), ("label", LABELS), ("added", ADDED)):
        if rng.random() < 0.9 or key == "kind":
            it[key] = pick(pool)
    if rng.random() < 0.05:
        it["extra"] = 1
    return it


def ser(x):
    return json.loads(json.dumps(x, sort_keys=False, default=repr))


def run_case():
    mode = rng.random()
    p = blocklist.PATH
    if p.is_dir():
        p.rmdir()
    elif p.exists():
        p.unlink()
    if mode < 0.12:
        pass                                                      # no file
    elif mode < 0.16:
        p.mkdir()                                                 # exists but cannot be read as a file (OSError)
    else:
        r = rng.random()
        if r < 0.06:
            text = pick(["{not json", "", "[", "\ufeff[]", "null"])
        elif r < 0.12:
            text = json.dumps(pick([{"kind": "mac"}, "x", 5, None, {}]))
        else:
            text = json.dumps([entry() for _ in range(rng.randrange(0, 7))])
        p.write_text(text, encoding="utf-8")
        t = 1_700_000_000 + rng.randrange(0, 50)
        os.utime(p, (t, t))
    stamp = blocklist._stamp()
    sentinel = [{"id": "cached"}]
    c = rng.random()
    if c < 0.3:
        blocklist._cache.update(stamp=stamp, items=sentinel)            # valid cache (or None stamp)
    elif c < 0.5:
        blocklist._cache.update(stamp=None, items=sentinel)
    elif c < 0.7:
        blocklist._cache.update(stamp=(stamp or 0) + 1, items=sentinel)
    else:
        blocklist._cache.update(stamp=stamp, items=[{"id": "old"}]) if rng.random() < 0.3 else blocklist._cache.update(stamp=-5.0, items=[])
    try:
        res = blocklist.list_items()
        again = blocklist.list_items()
        out = [ser(res), res is sentinel, again is res, ser(blocklist._cache["items"]), blocklist._cache["stamp"] == stamp, blocklist._cache["stamp"] is None]
    except Exception as exc:
        out = {"exception": type(exc).__name__}
    return out


cases = [run_case() for _ in range(N)]
digests = [hashlib.sha1(json.dumps(c).encode()).hexdigest()[:12] for c in cases]
out = {"digests": digests, "sample": cases[:40]}
out = json.loads(json.dumps(out))
if os.environ.get("BLOCKLIST_ITEMS_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(out, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want["digests"]) == len(digests) == N
for i, (x, y) in enumerate(zip(digests, want["digests"])):
    assert x == y, "case %d differs: %s" % (i, json.dumps(cases[i])[:500])
assert out["sample"] == want["sample"]
assert not any(isinstance(c, dict) for c in cases)
assert sum(1 for c in cases if c[1]) > 300 and sum(1 for c in cases if len(c[0]) >= 3) > 80 and sum(1 for c in cases if c[0] == [] and not c[1]) > 300, "scenarios too uniform"
assert sum(1 for c in cases if c[5]) > 200 and sum(1 for c in cases if c[2]) > 2000
assert any(it.get("kind") == "ip" and it.get("value") == "192.168.1.5" for c in cases for it in c[0]) and any(len(it.get("label", "")) == 80 for c in cases for it in c[0])
assert any(it["id"] == "12" for c in cases for it in c[0]) and any(it["id"] == "" for c in cases for it in c[0])
print("TUTTO OK")
