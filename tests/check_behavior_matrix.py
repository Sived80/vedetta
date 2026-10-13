"""The behaviour matrix is well formed, every check it names exists and every scenario passes. What is not covered is only reported, never hidden,
but it cannot grow unnoticed: a new row without a check raises the ceiling below on purpose."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))
import behavior_matrix as bm  # noqa: E402
from behavior_scenarios import SCENARIOS  # noqa: E402

MAX_UNTESTED = 12   # rows without a check today: lower it as cases get covered

matrix = bm.load()
assert not bm.problems(matrix), bm.problems(matrix)

rows = matrix["behaviors"] + matrix["overlaps"]
for row in rows:
    check = row.get("check")
    assert check is None or check in SCENARIOS or (ROOT / check).exists(), "unknown check %r" % check
for name in {r["check"] for r in rows if r.get("check") in SCENARIOS}:
    SCENARIOS[name]()
assert len(bm.untested(matrix)) <= MAX_UNTESTED, bm.untested(matrix)

# the shape of the tool: a pair is decided once, the overlaps decided are not asked again
decided = bm.decided(matrix)
assert all(frozenset(p[:2]) not in decided for p in bm.undecided_pairs(matrix))
assert len(bm.undecided_pairs(matrix)) + len(decided & {frozenset(p[:2]) for p in bm.candidate_pairs(matrix)}) == len(bm.candidate_pairs(matrix))
print("TUTTO OK")
