"""Names used and never defined in the ES modules of the page: a module that uses a name of another module without importing it fails only when that line runs (a ReferenceError in the browser, not when the page
loads, so the boot check does not see it). tools/js_undefined_refs.js reads every module with the parser that Node carries (acorn, through --expose-internals: nothing to install) and reports each name that is
neither imported, nor declared in an enclosing scope, nor a global of the page. The check is skipped where Node, or that parser, is not there."""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if not shutil.which("node"):
    print("SKIP: node is not installed")
    sys.exit(0)
proc = subprocess.run(["node", "--expose-internals", str(ROOT / "tools" / "js_undefined_refs.js")], capture_output=True, text=True, timeout=120)
out = proc.stdout + proc.stderr
if "SKIPPED" in out:
    print("SKIP: the parser of Node is not reachable")
    sys.exit(0)
assert proc.returncode == 0, "names used and not defined:\n" + out[-1500:]
assert "names used and not defined: 0" in out, out[-500:]
print("TUTTO OK")
