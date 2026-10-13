"""The clues that decide the group of a device have a sign: a clue in favour adds, a clue against takes away (weight of evidence: Good; Fellegi-Sunter agreement and disagreement weights; MYCIN belief and disbelief).
One function (family_best) says which clue of a family counts - the strongest, in favour or against - and it is used by BOTH the sum of the points (_aggregate) and the mark "counted" of the evidence shown (device_debug), which
used to repeat the same calculation. As long as no clue is against, everything is as it always was: the reference below is the calculation as it was written before, and the two must give the same on any list of clues."""
import os
import random
import sys
import tempfile

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import ha_data  # noqa: E402
from app.ha import ha_type_evidence as T  # noqa: E402
from app.ha.device_debug import _shown_evidence  # noqa: E402


def row(group, family, pts, source="x"):
    return {"group": group, "family": family, "pts": pts, "source": source}


def legacy_aggregate(ev):
    """The sum of the points as it was written before the clues had a sign."""
    best = {}
    for e in ev:
        key = (e["group"], e["family"])
        best[key] = max(best.get(key, 0), e["pts"])
    scores, port_total = {}, {}
    for (group, family), pts in best.items():
        if family.startswith("port:"):
            port_total[group] = port_total.get(group, 0) + pts
        else:
            scores[group] = scores.get(group, 0) + pts
    for group, pts in port_total.items():
        scores[group] = scores.get(group, 0) + min(pts, T.W_PORTS_MAX)
    return scores


# 1. nothing against: the same as always, on any list of clues (also with repeated families, zero points and ports over their cap)
rng = random.Random(20261012)
GROUPS, FAMILIES = ["router", "server", "pc", "iot", "media"], ["words", "svc:a", "svc:b", "cast", "port:80", "port:22", "port:445", "model", "platform"]
for _ in range(3000):
    ev = [row(rng.choice(GROUPS), rng.choice(FAMILIES), rng.choice([0, 1, 2, 3, 4, 8, 10])) for _ in range(rng.randrange(0, 14))]
    assert T._aggregate(ev) == legacy_aggregate(ev), ev

# 2. the strongest clue of a family counts, in favour or against; the families add up
assert T.family_best([row("router", "f", 2), row("router", "f", 8), row("router", "f", 4)]) == {("router", "f"): 8}
assert T.family_best([row("router", "f", -2), row("router", "f", -8), row("router", "f", -4)]) == {("router", "f"): -8}, "against: the strongest too"
assert T.family_best([row("router", "f", -4), row("router", "f", 4)]) == T.family_best([row("router", "f", 4), row("router", "f", -4)]) == {("router", "f"): 4}, "a tie goes to the clue in favour, in any order"
assert T.family_best([row("router", "f", 0)]) == {("router", "f"): 0}, "a clue of zero points keeps its family (the group appears in the scores)"
assert T._aggregate([row("router", "a", 4), row("router", "b", -3)]) == {"router": 1}, "in favour 4, against 3: 1"
assert T._aggregate([row("router", "a", 4), row("router", "b", -3), row("router", "b", -1)]) == {"router": 1}, "two clues of the same family against count once"
assert T._aggregate([row("pc", "a", 2), row("router", "b", -3)]) == {"pc": 2, "router": -3}, "a group can go below zero"
assert T._aggregate([row("pc", "port:80", 4), row("pc", "port:22", 4), row("pc", "port:445", 4), row("pc", "x", -2)]) == {"pc": T.W_PORTS_MAX - 2}, "the cap of the ports is only on the ports"

# 3. the evidence shown: the clue that counts is marked, also against; the others of its family are repetitions
shown = _shown_evidence([row("router", "a", 4), row("router", "b", -1, "weak"), row("router", "b", -3, "strong"), row("router", "a", 2)])
assert {(e["source"], e["pts"]): e["counted"] for e in shown} == {("x", 4): True, ("weak", -1): False, ("strong", -3): True, ("x", 2): False}, shown
assert [e["pts"] for e in shown] == [4, 2, -1, -3] or [e["pts"] for e in shown] == [4, 2, -3, -1], "in favour first, against last"

# 4. a group that ends below the minimum is not chosen, and the decision reads the net points
original = T.type_evidence
try:
    T.type_evidence = lambda device, adapter=None, kinds_out=None: [row("router", "role", 10), row("router", "law", -9)]
    assert ha_data.infer_type({"ip": "10.0.0.1"}, None) == "generic", "10 in favour, 9 against: 1 point, below the minimum"
    T.type_evidence = lambda device, adapter=None, kinds_out=None: [row("router", "role", 10), row("router", "law", -3)]
    assert ha_data.infer_type({"ip": "10.0.0.1"}, None) == "router"
finally:
    T.type_evidence = original
print("TUTTO OK")
