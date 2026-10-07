"""The front-end of /ha is kept in parts (app/frontend/ha/js, app/frontend/ha/css) and served joined (app/assets.py).
Checks: the joined script is valid JavaScript, it opens and closes one function, the page asks for the joined files with a version
that changes with the content, and no stale copy of ha.js / ha.css is left in the static folder (it would never be served)."""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "vedetta"
sys.path.insert(0, str(ROOT))
from app import assets  # noqa: E402

js, css = assets.bundle("ha/ha.js"), assets.bundle("ha/ha.css")
assert len(assets.parts("ha/ha.js")) >= 1 and len(assets.parts("ha/ha.css")) >= 1
assert "(function () {" in js[:1000] and js.rstrip().endswith("})();"), "the script must open and close one function"
assert css.count("{") == css.count("}"), "unbalanced braces in the joined style"
for name in ("ha/ha.js", "ha/ha.css"):
    assert not (ROOT / "app" / "static" / name).exists(), "a stale %s in static/ would be hidden by the joined one" % name
    for p in assets.parts(name):
        raw = p.read_bytes()
        assert raw.endswith(b"\n"), "%s must end with a new line (the next part starts on its own line)" % p.name
v1 = assets.version("ha/ha.js")
assert v1 == assets.version("ha/ha.js") and len(v1) == 12

# the version follows the content
tmp = Path(tempfile.mkdtemp())
try:
    shutil.copytree(assets.FRONTEND, tmp / "frontend")
    old = assets.FRONTEND
    assets.FRONTEND = tmp / "frontend"
    assets._cache.clear()
    before = assets.version("ha/ha.js")
    last = assets.parts("ha/ha.js")[-1]
    last.write_text(last.read_text(encoding="utf-8") + "// changed\n", encoding="utf-8")
    os.utime(last, None)
    assert assets.version("ha/ha.js") != before, "the version must change with the content"
finally:
    assets.FRONTEND = old
    assets._cache.clear()
    shutil.rmtree(tmp, ignore_errors=True)

# the app serves the joined files at the old addresses, before the static folder (which would answer 404)
import asyncio  # noqa: E402
from app import main  # noqa: E402
paths = [getattr(r, "path", None) for r in main.app.routes]
for name in assets.BUNDLES:
    i = paths.index("/static/" + name)
    assert i < paths.index("/static"), "the route of %s must come before the static folder" % name
    resp = asyncio.run(main.app.routes[i].endpoint())
    assert resp.body.decode("utf-8") == assets.bundle(name) and resp.media_type == assets.media_type(name)
    assert main.static_version(name) == assets.version(name)

if shutil.which("node"):
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(js)
    try:
        proc = subprocess.run(["node", "--check", f.name], capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr[-800:]
    finally:
        os.unlink(f.name)
print("TUTTO OK")
