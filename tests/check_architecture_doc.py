"""docs/ARCHITECTURE.md is written by tools/make_architecture.py (the index of the modules and the layers come from the code): it must be exactly what the script writes now.
If this fails, run  python tools/make_architecture.py --write  and commit the file."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import make_architecture  # noqa: E402

want = make_architecture.render()
have = (ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8") if (ROOT / "docs" / "ARCHITECTURE.md").exists() else ""
assert have.replace("\r\n", "\n") == want, "docs/ARCHITECTURE.md is out of date: run  python tools/make_architecture.py --write"
for line in want.splitlines():
    if line.startswith("| `") and line.rstrip().endswith("| — |"):
        raise AssertionError("a module has no docstring: " + line)
print("TUTTO OK")
