"""Golden-master test of identity_shift.judge (are two MACs behind a card the same device, different devices, or is it not known?): 5000 generated pairs of profiles - private and
shared MACs, a network role on either side, equal and different DHCP and Bonjour names, Home Assistant models with parts missing, DHCP families, recognised groups, identical profiles -
must give exactly the verdict, reasons and vetoes (and their ORDER) stored in tests/golden/judge.json, written from the code as it was before the chain of steps was rewritten as guard clauses.
Regenerate only on purpose:  JUDGE_GOLDEN_UPDATE=1 python tests/check_judge_golden.py"""
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import identity_shift  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "judge.json"
N = 5000
rng = random.Random(31415)
HA = [None, (None, None, None), ("Acme", "M1", "x"), ("Acme", "M1", "y"), ("Acme", "M2", "x"), ("Acme", None, None), (None, "M1", None), (None, None, "z"), ("Other", "M1", "x")]


def pick(seq):
    return seq[rng.randrange(len(seq))]


def profile(i):
    return {"mac": "m%d" % i, "private": pick([False, False, False, True]), "dhcp_name": pick([None, "", "iphone", "pc-1", "tv"]), "mdns_name": pick([None, "", "a", "b"]),
            "ha": pick(HA), "family": pick([None, "ios", "android", "windows", "console", "linux"]), "grp": pick([None, "generic", "pc", "media", "phone"])}


out = []
for _ in range(N):
    a, b = profile(1), profile(2)
    if rng.random() < 0.12:
        b = dict(a, mac="m2")
    shared = set(rng.sample(["m1", "m2", "m3"], rng.randrange(0, 3))) if rng.random() < 0.25 else set()
    args = (a, b, shared, rng.random() < 0.1, rng.random() < 0.1)
    try:
        out.append([[a, b, sorted(shared), args[3], args[4]], identity_shift.judge(*args)])
    except Exception as exc:
        out.append([[a, b, sorted(shared), args[3], args[4]], {"exception": type(exc).__name__}])
out = json.loads(json.dumps(out, sort_keys=True))
if os.environ.get("JUDGE_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(out, sort_keys=True, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want) == len(out) == N
for i, (x, y) in enumerate(zip(out, want)):
    assert x == y, "case %d differs: %s" % (i, json.dumps([x, y])[:500])
res = [r[1] for r in out]
verdicts = {r.get("verdict") for r in res}
assert {"same", "different", "unknown"} <= verdicts, verdicts
assert not any("exception" in r for r in res)
assert sum(1 for r in res if r["verdict"] == "different") > 150 and sum(1 for r in res if r["verdict"] == "same") > 300 and sum(1 for r in res if r["vetoes"]) > 500, "scenarios too uniform"
assert {len(r["reasons"]) for r in res if r["verdict"] == "different"} >= {2, 3}
print("TUTTO OK")
