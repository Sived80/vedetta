"""Golden-master test of evidence.name_evidence (what decided the name of a device, how sure the app is, which candidates were rejected), written from the code as it was before the
function was split into small guarded helpers: 5000 generated debug blocks and devices - every source (user, weak, a real source, an unknown one, none), the shown name equal to the IP or
to the brand (spaces and capitals included), placeholders, candidates with missing/equal/cleaned-equal values, malformed candidates, non-string values, weights around the clamp limits
(`naming.PRIORITY` is replaced by a fixed table) - must give exactly the results stored in tests/golden/name_evidence.json (exceptions included, by type; the key order counts).
Regenerate only on purpose:  NAME_EVIDENCE_GOLDEN_UPDATE=1 python tests/check_name_evidence_golden.py"""
import json
import os
import random
import sys
import types
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.recognition import evidence  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "name_evidence.json"
N = 5000
rng = random.Random(1357911)
PRIORITY = {"user": 100, "ha": 90, "mdns": 70, "dhcp": 50, "web": 30, "low": 12, "zero": 0, "neg": -7, "weak": 40, "huge": 140, "edge20": 20, "edge95": 95, "float": 55.5, "": 60, None: 33}
evidence.naming = types.SimpleNamespace(PRIORITY=PRIORITY)


def pick(seq):
    return seq[rng.randrange(len(seq))]


SOURCES = [None, None, "", "user", "user", "user", "weak", "weak", "weak", None, "ha", "mdns", "dhcp", "web", "low", "zero", "neg", "huge", "edge20", "edge95", "float", "other"]
NAMES = [None, "", "192.168.1.5", "Sony", " sony ", "SONY", "Sony", " sony ", "Acme", "Sony", "Sony TV", "Living room", "Cucina", "x", 5, "Sony  "]
BRANDS = [None, "", " ", "Sony", "sony", " SONY ", "Acme", 5, "Sony", "sony", "Acme"]
RAWS = [None, "", "Sony", "sony", " sony ", "Sony TV", "Living room", "Cucina", "192.168.1.5", "other", 5]
CLEANED = [None, "", "Sony", "sony", "SONY", "Sony TV", "sony tv", "living room", "x"]


def candidate():
    r = rng.random()
    if r < 0.03:
        return pick([None, "text", 7])
    c = {"source": pick(["ha", "dhcp", "web", "mdns", None]), "raw": pick(RAWS)}
    if rng.random() < 0.85:
        c["cleaned"] = pick(CLEANED)
    if rng.random() < 0.05:
        del c["source"]
    return c


def case():
    dn = {}
    if rng.random() < 0.95:
        dn["shown"] = pick(NAMES)
    if rng.random() < 0.9:
        dn["source"] = pick(SOURCES)
    if rng.random() < 0.7:
        dn["placeholder"] = pick([True, False, None, 0, 1, "yes"])
    r = rng.random()
    if r < 0.8:
        dn["candidates"] = [candidate() for _ in range(rng.randrange(0, 5))]
    elif r < 0.9:
        dn["candidates"] = None
    device = {}
    if rng.random() < 0.8:
        device["ip"] = pick([None, "192.168.1.5", "10.0.0.1", ""])
    if rng.random() < 0.85:
        device["brand"] = pick(BRANDS)
    if rng.random() < 0.02:
        dn = pick([{}, {"shown": "A"}])
    return dn, device


def run(dn, device):
    try:
        return {"res": evidence.name_evidence(dn, device)}
    except Exception as exc:  # noqa: BLE001
        return {"exc": type(exc).__name__}


cases = []
for _ in range(N):
    dn, device = case()
    cases.append({"debug_name": dn, "device": device, "out": run(dn, device)})
got = [json.dumps(c) for c in cases]
if os.environ.get("NAME_EVIDENCE_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(got), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want) == len(got) == N
for i, (x, y) in enumerate(zip(got, want)):
    assert x == y, "case %d differs: %s <> %s" % (i, x[:500], y[:500])

res = [c["out"]["res"] for c in cases if "res" in c["out"]]
basis = {}
for r in res:
    basis[r["basis"]] = basis.get(r["basis"], 0) + 1
assert all(basis.get(b, 0) > 150 for b in ("ip", "manual", "brand", "placeholder", "source", "unknown")), "too uniform: %s" % basis
assert sum(1 for c in cases if "exc" in c["out"]) > 40 and sum(1 for r in res if r["rejected"]) > 1500
assert {r["certainty"] for r in res} >= {0, 10, 15, 20, 56, 95, 100}, sorted({r["certainty"] for r in res})
assert sum(1 for r in res if r["placeholder"]) > 500 and sum(1 for r in res if r["basis"] == "source" and r["rejected"]) > 300
print("TUTTO OK")
