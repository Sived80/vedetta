"""Golden-master test of arpplan.plan (which addresses the periodic ARP check asks): 3000 generated cases - networks from a /8 to a /32 and unreadable or IPv6 ones, own address missing, in
the network, outside it or invalid, known devices (repeated, invalid, IPv6, inside and outside the network, more than the limit), per-block "last asked" times with ties and unknown blocks,
and the `force` flag - must give exactly the plans stored in tests/golden/arpplan_plan.json, written from the code as it was before the function was split (the key order of the
dictionaries and the order of every list count).
Regenerate only on purpose:  ARPPLAN_GOLDEN_UPDATE=1 python tests/check_arpplan_plan_golden.py"""
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import arpplan  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "arpplan_plan.json"
N = 3000
rng = random.Random(4242424)

CIDRS = ["192.168.1.0/24", "192.168.1.5/24", "10.0.0.0/16", "10.0.3.0/20", "10.0.0.0/8", "172.16.0.0/12", "192.168.1.0/25", "bad", "", "::1/64", "fe80::/10", "10.0.0.0/32",
         "0.0.0.0/0", "10.0.0.0/16", "10.0.0.0/16", "10.0.0.0/20", "10.0.0.0/23", "192.168.1.0/24", "10.1.0.0/17"]
OWNS = [None, "", "10.0.5.7", "10.1.5.7", "192.168.1.9", "garbage", "fe80::1", "10.0.0.255", "10.0.5.7", "10.0.5.7", "10.0.1.1", "192.168.1.9", "172.16.4.4", "10.0.15.2"]
TS_VALUES = [0.0, 1.0, 2.0, -1.0, 5.5, 100.0]


def pick(seq):
    return seq[rng.randrange(len(seq))]


def known_ip():
    r = rng.random()
    if r < 0.45:
        return "10.0.%d.%d" % (rng.randrange(0, 24), rng.randrange(0, 256))
    if r < 0.55:
        return "10.1.%d.%d" % (rng.randrange(0, 12), rng.randrange(0, 256))
    if r < 0.7:
        return "192.168.1.%d" % rng.randrange(0, 256)
    if r < 0.8:
        return "172.%d.%d.1" % (rng.randrange(16, 32), rng.randrange(0, 5))
    return pick(["bad", "", "fe80::1", "::1", None, "10.0.0.0", "300.1.1.1", "10.0.5.7", "192.168.1.9"])


def block_name():
    r = rng.random()
    if r < 0.6:
        return "10.0.%d.0/24" % rng.randrange(0, 24)
    if r < 0.8:
        return "10.1.%d.0/24" % rng.randrange(0, 12)
    if r < 0.9:
        return "192.168.1.0/24"
    return pick(["172.16.0.0/24", "junk"])


out = []
stats = {"none": 0, "narrow": 0, "known_only": 0, "blocks": 0, "force": 0, "max_known": 0, "fresh": 0, "own_chosen": 0, "two_blocks": 0, "exc": 0, "done": 0, "tie": 0, "singles": 0}
for _ in range(N):
    cidr, own = pick(CIDRS), pick(OWNS)
    heavy = rng.random() < 0.03
    known = [known_ip() for _ in range(rng.randrange(0, 12) if not heavy else rng.randrange(700, 1400))]
    if heavy:
        known = ["10.0.%d.%d" % (rng.randrange(1, 24), rng.randrange(0, 256)) for _ in range(len(known))]
    if known and rng.random() < 0.3:
        known += known[:3]
    block_ts = {}
    for _ in range(rng.randrange(0, 14)):
        block_ts[block_name()] = pick(TS_VALUES)
    force = pick([False, False, False, True])
    args = (cidr, own, known, block_ts, force) if rng.random() < 0.85 else (cidr, own, known, block_ts)
    try:
        r = arpplan.plan(*args)
        out.append(r)
        if r is None:
            stats["none"] += 1
        else:
            stats["blocks" if r["blocks"] else "known_only"] += 1
            stats["fresh"] += bool(r["fresh"])
            stats["two_blocks"] += len(r["blocks"]) == 2
            stats["max_known"] += len(r["targets"]) - len(r["blocks"]) == arpplan.MAX_KNOWN
            stats["singles"] += len(r["targets"]) > len(r["blocks"]) and bool(r["blocks"])
            stats["done"] += r["done"] > 0
            stats["force"] += force and cidr.endswith("/24") and bool(r["blocks"]) and own is not None
    except Exception as exc:
        out.append({"exception": type(exc).__name__})
        stats["exc"] += 1

text_out = json.dumps(out)  # no sort_keys: the key order counts
if os.environ.get("ARPPLAN_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.parent.mkdir(exist_ok=True)
    GOLDEN.write_text(text_out, encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want) == len(out) == N
for i, (x, y) in enumerate(zip(out, want)):
    assert json.dumps(x) == json.dumps(y), "case %d differs: %s" % (i, json.dumps([x, y])[:600])
assert text_out == GOLDEN.read_text(encoding="utf-8"), "key order or formatting differs"
assert stats["none"] > 200 and stats["blocks"] > 600 and stats["known_only"] > 100 and stats["two_blocks"] > 400 and stats["fresh"] > 200, "too uniform: %s" % stats
assert stats["max_known"] > 5 and stats["singles"] > 300 and stats["done"] > 300 and stats["force"] > 20, "too uniform: %s" % stats
assert 0 <= stats["exc"] < 50, stats
print("TUTTO OK")
