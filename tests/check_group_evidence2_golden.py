"""Golden-master test of evidence.group_evidence, second reference (key order of the output kept, clue ordering and cut, defaults for missing keys): 5000 generated inputs -
chosen by hand, phones with and without a score, generic and tied groups, groups with zero points, many clues with equal points (stable order), more than four clues,
clues of other groups or not counted, missing keys, None containers, an unusual minimum score - must give exactly the output stored in tests/golden/group_evidence2.json,
written from the code as it was before the helpers were extracted.
Regenerate only on purpose:  GROUP2_GOLDEN_UPDATE=1 python tests/check_group_evidence2_golden.py"""
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.recognition import evidence  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "group_evidence2.json"
N = 5000
rng = random.Random(1357924)
GROUPS = ["router", "iot", "media", "phone", "camera", "generic", "pc"]


def pick(seq):
    return seq[rng.randrange(len(seq))]


def clue(chosen):
    e = {"source": pick(["dhcp", "mdns", "port", "http", "vendor"]), "pts": pick([1, 2, 2, 3, 3, 4, 5]),
         "group": chosen if rng.random() < 0.6 else pick(GROUPS), "counted": pick([True, True, False, None, 1, 0])}
    r = rng.random()
    if r < 0.05:
        del e["group"]
    elif r < 0.1:
        del e["counted"]
    return e


def case():
    scores = {g: pick([0, 0, -1, 1, 2, 3, 3, 5, 8, 10, 12, 12, 15]) for g in rng.sample(GROUPS, rng.randrange(0, 7))}
    if rng.random() < 0.2 and scores:
        top = max(scores.values())
        for g in list(scores)[:2]:
            scores[g] = top                       # a tie
    chosen = pick([None, "", "generic", "phone", "router", "iot", "media", "pc", "unknown"] + list(scores) * 2)
    ev = [clue(chosen or "generic") for _ in range(rng.randrange(0, 10))]
    debug = {"chosen": chosen, "scores": scores, "manual": pick([False, False, False, True, None, 0, 1]), "min_score": pick([None, None, 2, 3, 5, 0, 12]),
             "evidence": ev}
    r = rng.random()
    if r < 0.05:
        del debug["scores"]
    elif r < 0.1:
        debug["scores"] = None
    elif r < 0.15:
        debug["evidence"] = None
    elif r < 0.2:
        del debug["evidence"]
    elif r < 0.23:
        debug = {}
    device = {}
    if rng.random() < 0.55:
        device["is_mobile"] = pick([True, False, None])
        if rng.random() < 0.9:
            device["mobile_score"] = pick([None, 0, 1, 2, 4, 6, 8, 12])
        device["mobile_reason"] = pick([None, "name", "dhcp"])
    return debug, device


out = []
for _ in range(N):
    debug, device = case()
    try:
        out.append([debug, device, evidence.group_evidence(debug, device)])
    except Exception as exc:
        out.append([debug, device, {"exception": type(exc).__name__}])
out = json.loads(json.dumps(out, default=str))
if os.environ.get("GROUP2_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(out, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want) == len(out) == N
for i, (x, y) in enumerate(zip(out, want)):
    assert json.dumps(x) == json.dumps(y), "case %d differs: %s" % (i, json.dumps([x, y])[:600])
res = [r[2] for r in out]
bases = {r.get("basis") for r in res}
assert {"manual", "mobile", "none", "weak", "tie", "scored"} <= bases, bases
whys = {x["why"] for r in res for x in r.get("rejected", [])}
assert {"tie", "behind", "mobile", "weak"} <= whys, whys
assert sum(1 for r in res if "exception" in r) < 50, [r for r in res if "exception" in r][:2]
assert any(len(r.get("clues", [])) == 4 for r in res) and any(0 < len(r.get("clues", [])) < 4 for r in res) and any(r.get("clues") == [] for r in res)
assert any(r.get("reason") for r in res) and any(r.get("certainty") == 100 for r in res) and any(0 < r.get("certainty", 0) < 100 for r in res)
assert any(r.get("basis") == "scored" and r["certainty"] in (5, 99) for r in res)
print("TUTTO OK")
