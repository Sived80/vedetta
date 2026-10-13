"""Golden-master test of evidence.group_evidence (how sure the app is of the group of a device and which groups it rejected): 3000 generated inputs - chosen by hand,
mobile phones with and without a score, generic and tied groups, groups with no points, a chosen group missing from the scores, clues counted or not, an
unusual minimum score - must give exactly the output stored in tests/golden/group_evidence.json, written from the code as it was before the function was
rewritten without the ctx container.   Regenerate only on purpose:  GROUP_GOLDEN_UPDATE=1 python tests/check_group_evidence_golden.py"""
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.recognition import evidence  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "group_evidence.json"
N = 3000
rng = random.Random(2468013)
GROUPS = ["router", "iot", "media", "phone", "camera", "generic", "pc"]


def pick(seq):
    return seq[rng.randrange(len(seq))]


def case():
    scores = {g: pick([0, 0, 1, 2, 3, 3, 5, 8, 10, 12, 12, 15]) for g in rng.sample(GROUPS, rng.randrange(0, 6))}
    if rng.random() < 0.15 and scores:
        top = max(scores.values())
        for g in list(scores)[:2]:
            scores[g] = top                       # a tie
    chosen = pick([None, "generic", "phone", "router", "iot", "media", "pc"] + list(scores))
    debug = {"chosen": chosen, "scores": scores, "manual": pick([False, False, False, True, None]), "min_score": pick([None, None, 2, 3, 5, 0]),
             "evidence": [{"source": pick(["dhcp", "mdns", "port"]), "pts": rng.randrange(1, 6), "group": pick(GROUPS), "counted": pick([True, False])}
                          for _ in range(rng.randrange(0, 7))]}
    if rng.random() < 0.1:
        del debug["scores"]
    device = {}
    if rng.random() < 0.5:
        device["is_mobile"] = pick([True, False])
        device["mobile_score"] = pick([None, 0, 2, 4, 6, 8, 12])
        device["mobile_reason"] = pick([None, "nome", "dhcp"])
    return debug, device


out = []
for _ in range(N):
    debug, device = case()
    try:
        out.append([debug, device, evidence.group_evidence(debug, device)])
    except Exception as exc:
        out.append([debug, device, {"exception": type(exc).__name__}])
out = json.loads(json.dumps(out, sort_keys=True, default=str))
if os.environ.get("GROUP_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(out, sort_keys=True, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want) == len(out) == N
for i, (x, y) in enumerate(zip(out, want)):
    assert x == y, "case %d differs: %s" % (i, json.dumps([x, y])[:600])
res = [r[2] for r in out]
bases = {r.get("basis") for r in res}
assert {"manual", "mobile", "none", "weak", "tie", "scored"} <= bases, bases
assert not any("exception" in r for r in res), [r for r in res if "exception" in r][:2]
whys = {x["why"] for r in res for x in r.get("rejected", [])}
assert {"tie", "behind", "mobile", "weak"} <= whys, whys
print("TUTTO OK")
