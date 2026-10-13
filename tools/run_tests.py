"""Run all tests (tests/check_*.py, the JS translations check and the UI checks in tests/ui) from the vedetta/ folder.
Usage: python tools/run_tests.py [--serial] [--times] [--coverage]   (exits with 1 if anything fails)
The tests run in parallel (one process each: Python checks on most cores, UI checks 4 at a time): each one gets a data folder of its own
(VEDETTA_DATA_DIR), so none writes into the files of another or into the real config/ folder. --serial runs them one at a time, in
order (to see a failure alone); --times prints the slowest ones; --coverage measures which lines of vedetta/app the Python tests run
(then: python -m coverage combine && python -m coverage report --rcfile=tools/coveragerc)."""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import gate_rules
import gentle

ROOT = Path(__file__).resolve().parent.parent
SKIP = {"check_phase_d.py"}      # historical test no longer maintained
# The tests must not take the computer of the person who runs them: they start with a low priority on Windows (a child inherits the priority of its parent, so a test that starts
# other processes is gentle too) and only a few at a time (VEDETTA_TEST_JOBS raises or lowers the number of Python tests that run together).
LOW_PRIORITY = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
DEFAULT_JOBS = 4          # Python tests that run together (the limit on the processors, tools/gentle.py, comes first)
SLOW_FIRST = ("check_mask_log_templates.py",)   # the heaviest start first, so the others fill the time they take
TEST_TIMEOUT_S = 120             # one test never needs more than a few seconds; this only catches a test that is stuck


def jobs(coverage: bool = False) -> list[tuple[str, list[str]]]:
    out = []
    wrap = [sys.executable, "-m", "coverage", "run", f"--rcfile={ROOT / 'tools' / 'coveragerc'}"] if coverage else [sys.executable]
    for test in sorted((ROOT / "tests").glob("check_*.py")):
        if test.name not in SKIP:
            out.append((test.name, wrap + [str(test)]))
    if shutil.which("node"):
        out.append(("check_i18n_js.js", ["node", str(ROOT / "tests" / "check_i18n_js.js")]))
        out.append(("check_js_boot.js", ["node", str(ROOT / "tests" / "check_js_boot.js")]))
        # UI checks in a simulated browser (jsdom): skipped by themselves when jsdom is not installed (npm install in tests/ui)
        for ui in sorted((ROOT / "tests" / "ui").glob("check_*.js")):
            for lang in ("it", "en"):
                out.append((f"{ui.name} ({lang})", ["node", str(ui), lang]))
    out.sort(key=lambda j: 0 if j[0] in SLOW_FIRST else 1)
    return out


def run_one(name: str, cmd: list[str]) -> tuple[str, int, str, float]:
    gentle.wait_for_memory()      # never start a test while the memory of the computer is short
    data = tempfile.mkdtemp(prefix="vedetta-test-")
    started = time.monotonic()
    try:
        for attempt in (1, 2):
            try:
                proc = subprocess.run(cmd, cwd=ROOT / "vedetta", capture_output=True, text=True, timeout=TEST_TIMEOUT_S, creationflags=LOW_PRIORITY,
                                      env={**os.environ, "PYTHON": sys.executable, "VEDETTA_DATA_DIR": data})
                break
            except subprocess.TimeoutExpired:   # a stuck test must not freeze the run (the whole suite takes under a minute)
                if attempt == 2:
                    return name, 124, f"stuck: killed after {TEST_TIMEOUT_S} s, twice", time.monotonic() - started
                print("STUCK (killed after %d s, running it once more):" % TEST_TIMEOUT_S, name, flush=True)
        tail = (proc.stdout[-1500:] + proc.stderr[-600:]) if proc.returncode else ""
        if not proc.returncode and gate_rules.is_skip(proc.stdout):
            tail = "SKIP " + proc.stdout.strip().splitlines()[0][:120]      # it tested nothing (jsdom or a browser is missing): told, and a failure unless allowed
        return name, proc.returncode, tail, time.monotonic() - started
    finally:
        shutil.rmtree(data, ignore_errors=True)


def golden_problem_of_run() -> str | None:
    """The goldens that this run left changed or created, from git; a git that cannot answer is a problem too (no proof is not a green)."""
    status = subprocess.run(["git", "status", "--porcelain", "tests/golden"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if status.returncode:
        return "golden check impossible: " + (status.stderr.strip().splitlines() or ["git failed"])[0][:120]
    return gate_rules.golden_problem(status.stdout, allowed="--allow-golden-update" in sys.argv)


def main() -> int:
    gentle.limit_cpus()      # before any child is started: they all inherit the limit
    gentle.cap_memory()      # and the memory ceiling (a runaway test gets a MemoryError)
    serial = "--serial" in sys.argv
    coverage = "--coverage" in sys.argv
    if coverage:
        os.environ["COVERAGE_FILE"] = str(ROOT / ".coverage_data" / "cov")      # an absolute path: the tests run in vedetta/
    work = jobs(coverage)
    failed, times, skipped = [], [], []
    # Pure Python checks use most of the cores; the UI checks (a simulated browser with fixed waits) fail when more than 4 run at once,
    # so they get a pool of their own and the two pools work at the same time.
    cpus = os.cpu_count() or 4
    jobs_cap = int(os.environ.get("VEDETTA_TEST_JOBS") or DEFAULT_JOBS)
    py_workers = 1 if serial else max(1, min(jobs_cap, cpus - 6))   # 2 cores (CI): 1 + 1
    ui_workers = 1
    t0 = time.monotonic()

    def drain(items, n):
        with ThreadPoolExecutor(max_workers=n) as pool:
            for fut in as_completed([pool.submit(run_one, name, cmd) for name, cmd in items]):
                name, code, tail, took = fut.result()
                times.append((took, name))
                if not code and tail.startswith("SKIP"):
                    skipped.append(f"{name}: {tail[5:]}")
                if code:
                    failed.append(name)
                    print("FALLITO", name, "\n", tail)

    ui = [j for j in work if ".js" in j[0]]
    py = [j for j in work if ".js" not in j[0]]
    if serial:
        drain(work, 1)
    else:
        with ThreadPoolExecutor(max_workers=2) as both:
            for f in [both.submit(drain, py, py_workers), both.submit(drain, ui, ui_workers)]:
                f.result()
    workers = f"{py_workers}+{ui_workers}"
    if "--times" in sys.argv or serial:
        for took, name in sorted(times, reverse=True)[:6]:
            print(f"  {took:6.1f} s  {name}")
    print(f"({len(work)} prove in {time.monotonic() - t0:.0f} s, {workers} in parallelo)")
    if skipped:
        print(f"SALTATI ({len(skipped)}): " + "; ".join(sorted(skipped)[:4]) + (" ..." if len(skipped) > 4 else ""))
        if not os.environ.get("VEDETTA_ALLOW_SKIP"):      # a test that did not run is not a test that passed (set VEDETTA_ALLOW_SKIP=1 on a machine without jsdom or a browser)
            failed.append(f"{len(skipped)} test saltati")
    changed = golden_problem_of_run()
    if changed:      # also in the CI: a golden that a run creates or rewrites is a test that proved nothing (the file would be missing from the commit)
        print(changed)
        failed.append("golden cambiati")
    print("TUTTO OK" if not failed else "FALLITI: " + ", ".join(sorted(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
