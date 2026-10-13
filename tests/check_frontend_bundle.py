"""The front-end of /ha is kept in parts (app/frontend/ha/js: ES modules, app/frontend/ha/css: the style) and served by app/assets.py + main.py.
Checks: the style is joined and balanced and no stale copy of ha.css is left in the static folder (it would never be served); the modules are what a browser needs (a package.json that says "module", the entry
app.js, every import points to a file that exists and exports that name, every module is reached from the entry, each one is valid JavaScript); the page asks for the entry with a version that changes with the
content; the app serves the modules as JavaScript, always checked again (ETag, 304 when nothing changed) and before the static folder."""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "vedetta"
sys.path.insert(0, str(ROOT))
from app import assets  # noqa: E402

css = assets.bundle("ha/ha.css")
assert len(assets.parts("ha/ha.css")) >= 1
assert css.count("{") == css.count("}"), "unbalanced braces in the joined style"
assert not (ROOT / "app" / "static" / "ha" / "ha.css").exists(), "a stale ha.css in static/ would be hidden by the joined one"
assert not (ROOT / "app" / "static" / "ha" / "ha.js").exists(), "a stale ha.js in static/ would answer where the page now asks for modules"
for p in assets.parts("ha/ha.css") + assets.module_files():
    assert p.read_bytes().endswith(b"\n"), "%s must end with a new line" % p.name

# the modules: the graph of imports
assert '"type": "module"' in (assets.MODULES / "package.json").read_text(encoding="utf-8"), "package.json must say that the folder holds modules (Node and the tools read the files as modules)"
texts = {p.name: p.read_text(encoding="utf-8") for p in assets.module_files()}
assert "app.js" in texts, "the entry module is app.js"
IMPORT = re.compile(r'^import (?:\{([^}]*)\} from )?"\./([\w-]+\.js)";$', re.M)
EXPORT = re.compile(r"^export (?:async )?(?:function\s*\*?\s*|var |let |const )([\w$]+)", re.M)
VALUES = re.compile(r"^export (?:var|let|const) ([^;]*);", re.M)                      # `export var a = 1, b = 2;` exports both


def exported(t):
    names = set(EXPORT.findall(t))
    for m in VALUES.finditer(t):
        names |= set(re.findall(r"(?:^|,\s*)([\w$]+)\s*=", m.group(1)))
    return names


exports = {name: exported(t) for name, t in texts.items()}
for name, t in texts.items():
    for m in IMPORT.finditer(t):
        assert m.group(2) in texts, "%s imports %s, which does not exist" % (name, m.group(2))
        for n in (x.strip() for x in (m.group(1) or "").split(",") if x.strip()):
            assert n in exports[m.group(2)], "%s imports %s from %s, which does not export it" % (name, n, m.group(2))
reached, todo = set(), ["app.js"]
while todo:
    cur = todo.pop()
    if cur not in reached:
        reached.add(cur)
        todo += [m.group(2) for m in IMPORT.finditer(texts[cur])]
assert reached == set(texts), "modules that nothing imports (they would never run): %s" % sorted(set(texts) - reached)
assert not re.search(r"^\s*(?:export\s+default|module\.exports)", "".join(texts.values()), re.M)
importers = [name for name, tx in texts.items() if any(m.group(2) == "app.js" for m in IMPORT.finditer(tx))]
assert not importers, "nobody imports the entry (app.js is loaded with a version in its address: imported as ./app.js it would be a second copy that starts the page too early): %s" % importers
core_imports = [m.group(2) for m in IMPORT.finditer(texts["core.js"])]
assert not core_imports, "core.js is the base of everything: it imports nothing (%s)" % core_imports

# the version follows the content
v1 = assets.js_version()
assert v1 == assets.js_version() and len(v1) == 12
tmp = Path(tempfile.mkdtemp())
try:
    shutil.copytree(assets.MODULES, tmp / "js")
    old = assets.MODULES
    assets.MODULES = tmp / "js"
    assets._cache.clear()
    before = assets.js_version()
    last = assets.module_files()[-1]
    last.write_text(last.read_text(encoding="utf-8") + "// changed\n", encoding="utf-8")
    os.utime(last, None)
    assert assets.js_version() != before, "the version must change with the content"
finally:
    assets.MODULES = old
    assets._cache.clear()
    shutil.rmtree(tmp, ignore_errors=True)

# the app serves the style joined and the modules one by one, before the static folder (which would answer 404)
import asyncio  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app import main  # noqa: E402
paths = [getattr(r, "path", None) for r in main.app.routes]
for name in assets.BUNDLES:
    i = paths.index("/static/" + name)
    assert i < paths.index("/static"), "the route of %s must come before the static folder" % name
    resp = asyncio.run(main.app.routes[i].endpoint())
    assert resp.body.decode("utf-8") == assets.bundle(name) and resp.media_type == assets.media_type(name)
    assert main.static_version(name) == assets.version(name)
assert paths.index("/static/ha/js") < paths.index("/static"), "the modules must be served before the static folder"
assert main.static_version("ha/js") == assets.js_version()
client = TestClient(main.app)
r = client.get("/static/ha/js/app.js")
assert r.status_code == 200 and r.headers["content-type"].startswith("text/javascript"), (r.status_code, r.headers.get("content-type"))
assert r.headers["cache-control"] == "no-cache" and r.headers.get("etag"), "modules are always checked again: ETag + no-cache"
assert r.text == texts["app.js"]
again = client.get("/static/ha/js/app.js", headers={"If-None-Match": r.headers["etag"]})
assert again.status_code == 304, "an unchanged module costs a 304"
assert client.get("/static/ha/js/core.js").status_code == 200 and client.get("/static/ha/js/nope.js").status_code == 404

if shutil.which("node"):
    for p in assets.module_files():
        proc = subprocess.run(["node", "--check", str(p)], capture_output=True, text=True)
        assert proc.returncode == 0, p.name + ": " + proc.stderr[-800:]
print("TUTTO OK")
