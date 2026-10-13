"""One-command gate for every refactoring step. Prints a compact verdict; details only on failure.
  python tools/gate.py            run the whole suite + structure + size/complexity snapshot, compare with tools/gate_base.json
  python tools/gate.py --save     store the current snapshot as the new base (after an accepted step)
Exit code 0 only if all tests pass and nothing got worse than the base (max complexity, late imports, lines of the big files)."""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import gate_rules
import gentle
import nesting

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "tools" / "gate_base.json"
BIG = ["vedetta/app/state.py", "vedetta/app/scan/scanner.py", "vedetta/app/scan/probe.py", "vedetta/app/main.py"]


def sh(*cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")


def snapshot():
    snap = {"lines": {f: len((ROOT / f).read_text(encoding="utf-8").splitlines()) for f in BIG}}
    cc = sh(sys.executable, "-m", "radon", "cc", "-s", "-n", "C", "vedetta/app")   # grade C and worse (the project has C functions; D alone would show nothing)
    snap["worst"] = gate_rules.worst_complexity(cc.stdout)
    st = sh(sys.executable, "tests/check_structure.py").stdout
    m = re.search(r"(\d+) imports inside functions", st)
    snap["late_imports"] = int(m.group(1)) if m else -1
    snap.update(nesting.summary(ROOT))
    return snap


def clean_bytecode():
    """Old .pyc files must not decide a test (found: a mutation made in the same second and with the same size left a stale one)."""
    for top in ("vedetta", "tests", "tools"):
        for cache in (ROOT / top).rglob("__pycache__"):
            shutil.rmtree(cache, ignore_errors=True)


def main():
    gentle.limit_cpus()      # the gate and everything it starts share a few processors: the computer stays usable
    gentle.cap_memory()      # and a memory ceiling
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    clean_bytecode()
    real_data = gate_rules.folder_state(ROOT / "vedetta" / "config")
    t = sh(sys.executable, "tools/run_tests.py", *[a for a in sys.argv if a == "--allow-golden-update"])      # the test runner checks the goldens itself (the CI does too)
    ok = t.returncode == 0 and "TUTTO OK" in t.stdout
    tail = "\n".join(t.stdout.splitlines()[-25:])
    snap = snapshot()
    problems = [] if ok else ["tests failed"]
    too_deep = gate_rules.deep_problem(nesting.deep_functions(ROOT), nesting.ALLOWED_DEEP)
    if too_deep:
        problems.append(too_deep)
    touched = gate_rules.folder_problem(real_data, gate_rules.folder_state(ROOT / "vedetta" / "config"))
    if touched:
        problems.append(touched)
    if "--save" in sys.argv:
        BASE.write_text(json.dumps(snap, indent=1), encoding="utf-8")
    elif BASE.exists():
        base = json.loads(BASE.read_text(encoding="utf-8"))
        if snap["late_imports"] > base["late_imports"]:
            problems.append(f"late imports {base['late_imports']} -> {snap['late_imports']}")
        deeper = gate_rules.nesting_problem(snap, base)
        if deeper:
            problems.append(deeper)
        worse = gate_rules.complexity_problem(snap["worst"], base["worst"])
        if worse:
            problems.append(worse)
        for f, n in snap["lines"].items():
            if n > base["lines"].get(f, n) + 5 and sum(snap["worst"]) >= sum(base["worst"]):     # a file may grow when splitting makes the worst function simpler
                problems.append(f"{f} grew {base['lines'][f]} -> {n}")
    lines = " ".join(f"{Path(f).stem}={n}" for f, n in snap["lines"].items())
    print(("GATE OK" if not problems else "GATE FAIL: " + "; ".join(problems)) + f" | {lines} | worst cc {snap['worst']} | late imports {snap['late_imports']}")
    if not ok:
        print(tail)
    return 1 if problems else 0


sys.exit(main())
