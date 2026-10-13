"""The list of HTTP routes of the service (method + path) must not change when code is moved between modules: it is fixed in
tests/golden/routes.txt. A route added or removed on purpose: regenerate the file (see tests/check_probe_golden.py for the idea) and review the diff."""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import main  # noqa: E402

now = sorted(f"{sorted(getattr(r, 'methods', None) or [])} {r.path}" for r in main.app.routes)
want = [l for l in Path(__file__).parent.joinpath("golden", "routes.txt").read_text(encoding="utf-8").splitlines() if l.strip()]
assert now == want, "routes changed: +%s -%s" % (sorted(set(now) - set(want)), sorted(set(want) - set(now)))
print("TUTTO OK")
