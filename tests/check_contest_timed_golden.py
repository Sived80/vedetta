"""Golden-master test of macclassify._contest_timed (do two MACs overlap at an address and does it change hands between them in a continuous rhythm?): 5000 generated situations -
flips of the address between the two MACs in either direction and between other MACs or at other addresses, 0 to 9 flips, even and odd numbers of gaps (the median is told apart),
steps right at the median limit (899, 900, 901 s), flip gaps right at the limit (600, 601 s, missing), overlapping sessions right at the minimum (59, 60, 61 s, also summed from
two sessions), sessions at other addresses, a missing MAC (plain dictionary) or a defaultdict, unsorted flips - must give exactly the verdict (or the exception) stored in
tests/golden/contest_timed.json, written from the code as it was before the function was split into small steps.
Regenerate only on purpose:  CONTEST_GOLDEN_UPDATE=1 python tests/check_contest_timed_golden.py"""
import json
import os
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import macclassify  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "contest_timed.json"
N = 5000
rng = random.Random(24601)
BASE = 1_700_000_000


def pick(seq):
    return seq[rng.randrange(len(seq))]


def case():
    ip, a, b, c = "10.0.0.5", "aa:00:00:00:00:01", "aa:00:00:00:00:02", "aa:00:00:00:00:03"
    clean = rng.random() < 0.4                                       # a plain contest: most flips and the overlap are well inside the limits
    ov = pick([60, 61, 300]) if clean else pick([0, 30, 59, 60, 61, 300])
    sess_a, sess_b = [(BASE, BASE + 500, ip)], [(BASE + 500 - ov, BASE + 1500, ip)]
    if rng.random() < 0.2:                                          # the same overlap summed from two sessions
        h = ov // 2
        sess_a, sess_b = [(BASE, BASE + 200, ip), (BASE + 1000, BASE + 1200, ip)], [(BASE + 200 - h, BASE + 300, ip), (BASE + 1200 - (ov - h), BASE + 1300, ip)]
    if rng.random() < 0.3:
        sess_a.append((BASE, BASE + 5000, "10.0.0.9"))               # another address: not counted
        sess_b.append((BASE, BASE + 5000, "10.0.0.9"))
    arp_sess = defaultdict(list) if rng.random() < 0.8 else {}
    arp_sess[a] = sess_a
    if clean or rng.random() < 0.98:
        arp_sess[b] = sess_b
    k = pick([6, 7, 8, 9]) if clean else pick([0, 1, 2, 4, 5, 6, 6, 7, 7, 8, 9])
    mode = pick(["even", "uneven", "uneven"]) if clean else pick(["even", "uneven", "uneven", "designed"])
    levels = [100, 600, 899, 900] if clean else [100, 600, 899, 900, 901, 1500]
    if mode == "even":
        steps = [pick(levels)] * k
    else:
        steps = [pick(levels) for _ in range(k)]
    if mode == "designed" and k >= 4:                                  # short and long gaps in equal number: the upper and the lower median fall on different sides of the limit
        steps = ([100] * (k // 2) + [901] * (k - k // 2))
        rng.shuffle(steps)
    flips, ts = [], BASE + 100
    for j in range(k):
        old, new = (a, b) if j % 2 == 0 else (b, a)
        if not clean and rng.random() < 0.1:
            old, new = new, old
        if not clean and rng.random() < 0.08:
            old, new = pick([(a, c), (c, b), (a, a), (c, a)])
        f = {"ip": ip, "old": old, "new": new, "ts": ts}
        g = pick([0, 100, 600, "none", "none"]) if clean else pick([0, 100, 599, 600, 601, 650, "none", "none"])
        if g != "none":
            f["gap"] = g
        elif not clean and rng.random() < 0.01:
            f["gap"] = None
        flips.append(f)
        ts += steps[j]
    if rng.random() < 0.3:
        rng.shuffle(flips)
    by_ip = defaultdict(list) if rng.random() < 0.5 else {}
    if flips or rng.random() < 0.5:
        by_ip[ip] = flips
    if rng.random() < 0.3:
        by_ip["10.0.0.9"] = [dict(f, ip="10.0.0.9") for f in flips[:3]]
    return ip, a, b, arp_sess, by_ip


out = []
for _ in range(N):
    ip, a, b, arp_sess, by_ip = case()
    try:
        r = macclassify._contest_timed(ip, a, b, arp_sess, by_ip)
    except Exception as exc:
        r = {"exception": type(exc).__name__}
    out.append([r, ip, a, b, {m: list(v) for m, v in arp_sess.items()}, {k: v for k, v in by_ip.items()}])
out = json.loads(json.dumps(out))
if os.environ.get("CONTEST_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(out, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want) == len(out) == N
for i, (x, y) in enumerate(zip(out, want)):
    assert x == y, "case %d differs: %s" % (i, json.dumps([x, y])[:500])
res = [o[0] for o in out]
exc = sum(1 for r in res if isinstance(r, dict))
assert 0 < exc < 250, exc
assert sum(1 for r in res if r is True) > 350 and sum(1 for r in res if r is False) > 2000, "scenarios too uniform"
assert len({len(o[5].get("10.0.0.5", [])) for o in out}) >= 8
print("TUTTO OK")
