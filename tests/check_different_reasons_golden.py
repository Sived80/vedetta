"""Golden-master test of identity_shift._different_reasons (the independent families of evidence that two profiles are different devices, in a fixed order): 5000 generated pairs
of profiles - equal and different DHCP families, recognised groups (None, "generic", real ones), DHCP and Bonjour names, Home Assistant models of length 3, 2, 1 and 0 with parts
missing, empty and identical profiles, a profile with a missing key - must give exactly the list (and the exception, when there is one) stored in tests/golden/different_reasons.json,
written from the code as it was before the chain of conditions was split into small named checks.
Regenerate only on purpose:  DIFFREASONS_GOLDEN_UPDATE=1 python tests/check_different_reasons_golden.py"""
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import identity_shift  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "different_reasons.json"
N = 5000
rng = random.Random(97531)
HA = [None, (), (None, None, None), ("Acme", "M1", "x"), ("Acme", "M1", "y"), ("Acme", "M2", "x"), ("Acme", None, None), (None, "M1", None), (None, None, "z"),
      ("Other", "M1", "x"), ("", "", "q"), ["Acme", "M1"], ("Acme",), (None, None), ("Acme", "M1")]


def pick(seq):
    return seq[rng.randrange(len(seq))]


def profile():
    p = {"family": pick([None, "", "ios", "android", "windows", "console"]), "grp": pick([None, "generic", "pc", "media", "phone", ""]),
         "dhcp_name": pick([None, "", "iphone", "pc-1", "tv"]), "mdns_name": pick([None, "", "a", "b"]), "ha": pick(HA)}
    if rng.random() < 0.01:
        del p[pick(list(p))]
    return p


out = []
counts = {}
for _ in range(N):
    a, b = profile(), profile()
    if rng.random() < 0.15:
        b = dict(a)
    elif rng.random() < 0.3:
        for k in a:                       # some fields in common, so that every check is decided alone
            if k in b and rng.random() < 0.6:
                b[k] = a[k]
    try:
        r = identity_shift._different_reasons(a, b)
        for x in r:
            counts[x] = counts.get(x, 0) + 1
    except Exception as exc:
        r = {"exception": type(exc).__name__}
    out.append([a, b, r])
out = json.loads(json.dumps(out))
if os.environ.get("DIFFREASONS_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(out, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want) == len(out) == N
for i, (x, y) in enumerate(zip(out, want)):
    assert x == y, "case %d differs: %s" % (i, json.dumps([x, y])[:500])
res = [o[2] for o in out]
assert set(counts) == {"dhcp_family", "group", "dhcp_name", "mdns_name", "ha_model"} and min(counts.values()) > 300, counts
assert sum(1 for r in res if r == []) > 300 and sum(1 for r in res if isinstance(r, list) and len(r) >= 3) > 100, "scenarios too uniform"
print("TUTTO OK")
