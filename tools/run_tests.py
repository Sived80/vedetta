"""Lancia tutti i test (tests/check_*.py e il controllo delle traduzioni JS) dalla cartella vedetta/.
Uso: python tools/run_tests.py   (esce con 1 se qualcosa fallisce)"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP = {"check_phase_d.py"}   # test storico non piu' mantenuto


def main() -> int:
    failed = []
    for test in sorted((ROOT / "tests").glob("check_*.py")):
        if test.name in SKIP:
            continue
        proc = subprocess.run([sys.executable, str(test)], cwd=ROOT / "vedetta", capture_output=True, text=True)
        if proc.returncode:
            failed.append(test.name)
            print("FALLITO", test.name, "\n", proc.stdout[-600:], proc.stderr[-600:])
    if shutil.which("node"):
        proc = subprocess.run(["node", str(ROOT / "tests" / "check_i18n_js.js")], cwd=ROOT / "vedetta", capture_output=True, text=True)
        if proc.returncode:
            failed.append("check_i18n_js.js")
            print(proc.stdout[-600:], proc.stderr[-600:])
    print("TUTTO OK" if not failed else "FALLITI: " + ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
