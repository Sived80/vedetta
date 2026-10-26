"""The rules that keep the gate from saying «green» without proof (tools/gate_rules.py, used by tools/gate.py and tools/run_tests.py). Found by the global review of 2026-10-11:
a golden that is missing is created again and the test passes; the UI tests print SKIP and exit 0 when jsdom is missing; the complexity check looked at grade D only, where nothing is.
Pure functions, tested here with the shapes of the real output."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import gate_rules as g  # noqa: E402

# 1) a skipped test is told apart from a passed one (the UI tests and the browser test print SKIP on the first line)
assert g.is_skip("SKIP: jsdom is not installed (run `npm install` in tests/ui to enable this check)\n")
assert g.is_skip("some warning\nSKIP: no Chrome or Edge found\n")
assert not g.is_skip("TUTTO OK\n") and not g.is_skip("the word SKIP in a sentence is not a skip\n") and not g.is_skip("")

# 2) a golden that changed or was created is a problem; other changes are not
porcelain = " M tests/golden/full_ports.json\n?? tests/golden/new_one.json\n M vedetta/app/state.py\n?? tests/check_new.py\n D tests/golden/old.json\n"
assert g.dirty_goldens(porcelain) == ["tests/golden/full_ports.json", "tests/golden/new_one.json", "tests/golden/old.json"], g.dirty_goldens(porcelain)
assert g.dirty_goldens("") == [] and g.dirty_goldens(" M vedetta/app/state.py\n") == []
assert g.dirty_goldens('R  "tests/golden/a b.json" -> tests/golden/c.json\n') == ["tests/golden/c.json"]

# 2b) the message of that problem, shared by the gate and by the test runner (so the CI sees it too); allowed on purpose it is no problem
assert g.golden_problem("", allowed=False) is None and g.golden_problem(" M vedetta/app/state.py\n", allowed=False) is None
assert g.golden_problem(porcelain, allowed=True) is None
msg = g.golden_problem(porcelain, allowed=False)
assert msg and "golden changed or created" in msg and "tests/golden/full_ports.json" in msg and "--allow-golden-update" in msg, msg
assert "..." not in msg, "three goldens are all named: " + msg
four = g.golden_problem(" M tests/golden/a.json\n M tests/golden/b.json\n M tests/golden/c.json\n?? tests/golden/d.json\n", allowed=False)
assert "..." in four and "tests/golden/c.json" in four and "tests/golden/d.json" not in four, "only the first three are named: " + four

# 3) the complexity of radon's output (grade C and worse), the five worst, and the comparison with the base
radon = ("vedetta\\app\\analysis\\status.py\n    F 18:0 assess - C (11)\nvedetta\\app\\recognition\\naming.py\n    F 99:0 clean_name - C (12)\n"
         "vedetta\\app\\x.py\n    F 5:0 big - D (23)\n")
assert g.worst_complexity(radon) == [11, 12, 23]
assert g.worst_complexity("") == []
assert g.complexity_problem([11, 12], [11, 12]) is None and g.complexity_problem([11], [11, 12]) is None
assert "max complexity" in g.complexity_problem([11, 14], [11, 12])
assert "more complex functions" in g.complexity_problem([11, 12, 11], [11, 12])
assert g.complexity_problem([11], []) is None, "no base yet: nothing to compare with"

# 4) the real data folder (vedetta/config) must be the same before and after the tests: a test run by hand without VEDETTA_DATA_DIR once wrote there
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402
folder = Path(tempfile.mkdtemp())
before = g.folder_state(folder)
assert before == {} and g.folder_state(folder / "missing") == {}
assert g.folder_problem(before, g.folder_state(folder)) is None
(folder / "vedetta.db").write_bytes(b"x")
assert "vedetta.db" in g.folder_problem(before, g.folder_state(folder)), "a created file is a problem"
mid = g.folder_state(folder)
(folder / "vedetta.db").write_bytes(b"xy")
assert "vedetta.db" in g.folder_problem(mid, g.folder_state(folder)), "a changed file is a problem"
(folder / "vedetta.db").unlink()
assert "vedetta.db" in g.folder_problem(mid, g.folder_state(folder)), "a removed file is a problem"

# 6) how many tests run together: the Python pool leaves 6 processors to the system, the UI pool takes a quarter of them; a CI runner with 2 cores gets 1 + 1,
#    --serial gets 1 + 1 whatever the machine, and the caps (VEDETTA_TEST_JOBS, VEDETTA_UI_JOBS) are never exceeded
assert g.worker_counts(20, False, 4, 3) == (4, 3), "this computer: 4 Python tests and 3 UI tests"
assert g.worker_counts(20, False, 8, 3) == (8, 3) and g.worker_counts(20, False, 4, 1) == (4, 1)
assert g.worker_counts(20, False, 100, 100) == (14, 5), "the caps are limited by the processors: 20 - 6 and 20 // 4"
assert g.worker_counts(2, False, 4, 3) == (1, 1), "a CI runner with 2 cores: 1 + 1, as before"
assert g.worker_counts(4, False, 4, 3) == (1, 1) and g.worker_counts(8, False, 4, 3) == (2, 2)
assert g.worker_counts(20, True, 4, 3) == (1, 1), "serial: one at a time"
assert g.worker_counts(1, False, 4, 3) == (1, 1), "never fewer than one"
print("TUTTO OK")
