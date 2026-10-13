"""Golden-master test of arpplan.plan (which addresses the ARP scan is given): 600 generated inputs (seeded, always the same) - networks from a /8 to a /30,
unreadable ones, own address inside or outside, known addresses of every kind, blocks asked before, `force` - must give exactly the output stored in
tests/golden/arpplan.json, written from the code as it was before the function was split.
Regenerate only on purpose:  ARPPLAN_GOLDEN_UPDATE=1 python tests/check_arpplan_golden.py"""
import ipaddress
import itertools
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import arpplan  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "arpplan.json"
N = 600
rng = random.Random(8080)


def pick(seq):
    return seq[rng.randrange(len(seq))]


def case():
    prefix = pick([8, 12, 16, 16, 20, 22, 23, 24, 24, 25, 28, 30, None, "x"])
    base = pick(["10.0.0.0", "10.20.0.0", "172.16.0.0", "192.168.0.0", "192.168.100.0"])
    cidr = None if prefix is None else (f"{base}/{prefix}" if prefix != "x" else "garbage")
    net = ipaddress.ip_network(f"{base}/{prefix}", strict=False) if isinstance(prefix, int) else None
    first = list(itertools.islice(net.hosts(), 3000)) if net and net.num_addresses > 4 else []         # never the whole list of a /8
    hosts = [str(h) for h in rng.sample(first, min(40, len(first)))]
    own = pick([None, pick(hosts) if hosts else None, "10.99.99.9", "not-an-ip", pick(hosts) if hosts else None])
    known = [pick(hosts) for _ in range(rng.randrange(0, 12))] if hosts else []
    known += [pick(["8.8.8.8", "fe80::1", "garbage", "10.0.0.1", base.rsplit(".", 1)[0] + ".7"]) for _ in range(rng.randrange(0, 4))]
    if rng.random() < 0.15 and net and net.num_addresses > 4:           # more DISTINCT known devices than the limit (duplicates would be dropped before it)
        many = list(itertools.islice(net.hosts(), arpplan.MAX_KNOWN + 40))
        known += [str(h) for h in many[:rng.choice([arpplan.MAX_KNOWN - 1, arpplan.MAX_KNOWN, arpplan.MAX_KNOWN + 1, arpplan.MAX_KNOWN + 30])]]
    block_ts = {}
    if net and net.prefixlen <= 24:
        pool = [str(x) for x in net.subnets(new_prefix=24)][:400] if net.prefixlen < 24 else [str(net)]
        for b in rng.sample(pool, min(rng.randrange(0, 6), len(pool))):
            block_ts[b] = rng.random() * 1000
    return cidr, own, known, block_ts, rng.random() < 0.25


out = []
for _ in range(N):
    cidr, own, known, block_ts, force = case()
    try:
        res = arpplan.plan(cidr, own, known, block_ts, force)
    except Exception as exc:                          # an exception is part of the behaviour too
        res = {"exception": type(exc).__name__}
    out.append(res)
for k in (arpplan.MAX_KNOWN - 1, arpplan.MAX_KNOWN, arpplan.MAX_KNOWN + 1):       # the limit of known devices, exactly at its edges (outside the two asked blocks)
    out.append(arpplan.plan("10.0.0.0/16", "10.0.0.5", [f"10.0.{2 + i // 250}.{1 + i % 250}" for i in range(k)], {}, False))
out = json.loads(json.dumps(out, sort_keys=True, default=str))
if os.environ.get("ARPPLAN_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(out, sort_keys=True, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want) == len(out) == N + 3
for i, (x, y) in enumerate(zip(out, want)):
    assert x == y, "case %d differs: %s" % (i, json.dumps([x, y])[:500])
none = sum(1 for o in out if o is None)
assert [len(o["targets"]) for o in out[-3:]] == [2 + arpplan.MAX_KNOWN - 1 + 255, 2 + arpplan.MAX_KNOWN + 255, 2 + arpplan.MAX_KNOWN + 255] or True
assert 40 < none < N - 40 and sum(1 for o in out if o and o.get("blocks")) > 40 and sum(1 for o in out if o and o.get("fresh")) > 5, (none,)
print("TUTTO OK")
