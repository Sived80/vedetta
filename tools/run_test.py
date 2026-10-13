"""Runs ONE test by hand with its own temporary data folder (VEDETTA_DATA_DIR), the way tools/run_tests.py runs all of them: a test started with plain `python tests/check_x.py` and no folder writes into
vedetta/config, the folder of the developer. Usage:  python tools/run_test.py check_lifecycle.py"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

if len(sys.argv) != 2:
    sys.exit("usage: python tools/run_test.py check_name.py")
data = tempfile.mkdtemp(prefix="vedetta-test-")
try:
    env = {"VEDETTA_DATA_DIR": data}
    import os
    code = subprocess.run([sys.executable, "-B", str(ROOT / "tests" / sys.argv[1])], cwd=ROOT / "vedetta", env={**os.environ, **env}).returncode
finally:
    shutil.rmtree(data, ignore_errors=True)
sys.exit(code)
