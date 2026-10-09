"""Run all tests (tests/check_*.py, the JS translations check and the UI checks in tests/ui) from the vedetta/ folder.
Usage: python tools/run_tests.py [--serial] [--times]   (exits with 1 if anything fails)
The tests run in parallel (one process each, up to 4): each one gets a data folder of its own
(VEDETTA_DATA_DIR), so none writes into the files of another or into the real config/ folder. --serial runs them one at a time, in
order (to see a failure alone); --times prints the slowest ones."""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP = {"check_phase_d.py"}      # historical test no longer maintained
SLOW_FIRST = ("check_mask_log_templates.py",)   # the heaviest start first, so the others fill the time they take


def jobs() -> list[tuple[str, list[str]]]:
    out = []
    for test in sorted((ROOT / "tests").glob("check_*.py")):
        if test.name not in SKIP:
            out.append((test.name, [sys.executable, str(test)]))
    if shutil.which("node"):
        out.append(("check_i18n_js.js", ["node", str(ROOT / "tests" / "check_i18n_js.js")]))
        # UI checks in a simulated browser (jsdom): skipped by themselves when jsdom is not installed (npm install in tests/ui)
        for ui in sorted((ROOT / "tests" / "ui").glob("check_*.js")):
            for lang in ("it", "en"):
                out.append((f"{ui.name} ({lang})", ["node", str(ui), lang]))
    out.sort(key=lambda j: 0 if j[0] in SLOW_FIRST else 1)
    return out


def run_one(name: str, cmd: list[str]) -> tuple[str, int, str, float]:
    data = tempfile.mkdtemp(prefix="vedetta-test-")
    started = time.monotonic()
    try:
        proc = subprocess.run(cmd, cwd=ROOT / "vedetta", capture_output=True, text=True,
                              env={**os.environ, "PYTHON": sys.executable, "VEDETTA_DATA_DIR": data})
        tail = (proc.stdout[-1500:] + proc.stderr[-600:]) if proc.returncode else ""
        return name, proc.returncode, tail, time.monotonic() - started
    finally:
        shutil.rmtree(data, ignore_errors=True)


def main() -> int:
    serial = "--serial" in sys.argv
    work = jobs()
    failed, times = [], []
    workers = 1 if serial else max(2, min(4, (os.cpu_count() or 4) - 2))   # more than 4 at once makes the UI checks (fixed waits) fail
    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run_one, name, cmd) for name, cmd in work]
        for fut in as_completed(futures):
            name, code, tail, took = fut.result()
            times.append((took, name))
            if code:
                failed.append(name)
                print("FALLITO", name, "\n", tail)
    if "--times" in sys.argv or serial:
        for took, name in sorted(times, reverse=True)[:6]:
            print(f"  {took:6.1f} s  {name}")
    print(f"({len(work)} prove in {time.monotonic() - t0:.0f} s, {workers} in parallelo)")
    print("TUTTO OK" if not failed else "FALLITI: " + ", ".join(sorted(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
