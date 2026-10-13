"""Golden-master test of macidentity.score and macidentity.link (are two MACs the same device? log2-odds, reasons, evidence flags, zones): 4000 generated pairs for `score` and 1200
generated populations of 0 to 6 MACs for `link` - fields in agreement and in disagreement (host name, fingerprint, client id), values that are rare, common or missing from the
estimate, sessions and plain first/last spans, gaps right at the hand-over limit (599, 600, 601 s), MACs active together, a given or an unknown `rel`, divisions by zero - must give
exactly the totals (every float), reasons, flags and ORDER stored in tests/golden/mac_identity.json, written from the code as it was before the functions were split.
Regenerate only on purpose:  MACIDENTITY_GOLDEN_UPDATE=1 python tests/check_mac_identity_golden.py"""
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import macidentity  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "mac_identity.json"
N_SCORE = 4000
N_LINK = 1200
rng = random.Random(8642)
POOL = {"hostname": [None, "", "pc", "tv", "phone", "cam"], "fingerprint": [None, "", "fp1", "fp2", "fp3"], "client_id": [None, "", "c1", "c2"]}
U_VALUES = [0.001, 0.02, 0.05, 0.1, 0.3, 0.5, 0.9, 0.95, 1.0, 0.0]
IPS = ["10.0.0.1", "10.0.0.2", "10.0.0.3"]


def pick(seq):
    return seq[rng.randrange(len(seq))]


def u_table():
    u = {}
    for f, vals in POOL.items():
        if rng.random() < 0.01:
            continue
        u[f] = {v: pick(U_VALUES[:-2] if rng.random() < 0.97 else U_VALUES) for v in vals if v and rng.random() < 0.8}
    return u


def fields(base=None):
    d = {}
    for f, vals in POOL.items():
        if rng.random() < 0.8:
            d[f] = base[f] if base is not None and f in base and rng.random() < 0.45 else pick(vals)
    return d


def sessions(start, end):
    return [(s, s + rng.randrange(0, 1500), tuple(rng.sample(IPS, rng.randrange(1, 3)))) for s in sorted(rng.randrange(start, end + 1) for _ in range(rng.randrange(1, 4)))]


def with_time(a, b):
    mode = pick(["none", "none", "a_only", "span", "span", "gap", "gap", "sessions", "sessions", "overlap"])
    if mode == "none":
        return
    if mode == "a_only":
        a["first"], a["last"] = 0, 100
        return
    if mode == "gap":
        g = pick([599, 600, 601, 0, 1, 5000])
        a["first"], a["last"] = 0, 100
        b["first"], b["last"] = 100 + g, 150 + g
        a["ips"], b["ips"] = tuple(rng.sample(IPS, rng.randrange(0, 3))), tuple(rng.sample(IPS, rng.randrange(0, 3)))
        if rng.random() < 0.3:
            a["first"], a["last"], b["first"], b["last"] = b["first"], b["last"], a["first"], a["last"]
        return
    if mode == "overlap":
        a["first"], a["last"] = 0, 500
        b["first"], b["last"] = pick([0, 100, 499, 500]), 900
        a["ips"], b["ips"] = tuple(rng.sample(IPS, rng.randrange(1, 3))), tuple(rng.sample(IPS, rng.randrange(1, 3)))
        return
    for x in (a, b):
        x["first"] = rng.randrange(0, 3000)
        x["last"] = x["first"] + rng.randrange(0, 2000)
        if mode == "sessions":
            x["sessions"] = sessions(x["first"], x["last"])
        elif rng.random() < 0.7:
            x["ips"] = tuple(rng.sample(IPS, rng.randrange(0, 3)))


def score_case():
    a = fields()
    b = fields(a)
    with_time(a, b)
    rel = pick([None, None, None, (True, None), (False, None), (False, 0), (False, 600), (False, 601), (False, 30.5), (True, 12)])
    u_handoff = pick([0.05, 0.05, 0.001, 0.01, 0.2, 0.5, 1.0, 0.0] if rng.random() < 0.5 else [0.05])
    return a, b, u_table(), u_handoff, rel


def link_case():
    macs = ["m%d" % i for i in range(rng.randrange(0, 7))]
    feats = {}
    shared = fields()
    for m in macs:
        x = fields(shared)
        other = {}
        with_time(x, other) if rng.random() < 0.6 else None
        feats[m] = x
    return feats


out = {"score": [], "link": []}
for _ in range(N_SCORE):
    a, b, u, uh, rel = score_case()
    try:
        r = list(macidentity.score(a, b, u, uh, rel))
    except Exception as exc:
        r = {"exception": type(exc).__name__}
    out["score"].append([r])
for _ in range(N_LINK):
    feats = link_case()
    try:
        r = macidentity.link(feats)
    except Exception as exc:
        r = {"exception": type(exc).__name__}
    out["link"].append(r)
out = json.loads(json.dumps(out))
if os.environ.get("MACIDENTITY_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(out, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want["score"]) == len(out["score"]) == N_SCORE and len(want["link"]) == len(out["link"]) == N_LINK
for kind in ("score", "link"):
    for i, (x, y) in enumerate(zip(out[kind], want[kind])):
        assert x == y, "%s case %d differs: %s" % (kind, i, json.dumps([x, y])[:600])
sc = [o[0] for o in out["score"] if isinstance(o[0], list)]
assert len(sc) > 3400, "too many exceptions (%d)" % (len(out["score"]) - len(sc))
why = " ".join(w for r in sc for w in r[1])
assert "attivi insieme" in why and "stesso client id attivo" in why and "uno inizia dove" in why and "uguale" in why and "diverso" in why, "scenarios too uniform"
assert sum(1 for r in sc if r[4]) > 150 and sum(1 for r in sc if not r[4]) > 1000 and sum(1 for r in sc if r[3]) > 500 and sum(1 for r in sc if not r[2]) > 100
assert sum(1 for r in sc if r[2] and not r[3]) > 300 and sum(1 for r in sc if r[0] > 5) > 100 and sum(1 for r in sc if r[0] < -2) > 300
assert sum(1 for r in sc if any("(+3.0)" in w for w in r[1])) > 20 and sum(1 for r in sc if any("uno inizia" in w and "(+3.0)" not in w for w in r[1])) > 20
lk = [r for r in out["link"] if isinstance(r, list)]
assert len(lk) > 1100 and sum(1 for r in lk if len(r) >= 3) > 400, "link scenarios too uniform"
zones = {p["zone"] for r in lk for p in r}
assert {"same", "possible", "different", "unrelated"} <= zones, zones
assert any(w.startswith("uno inizia") for r in lk for p in r for w in p["why"]) and any(w.startswith("attivi insieme") for r in lk for p in r for w in p["why"])
print("TUTTO OK")
