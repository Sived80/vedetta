"""Split a frontend JS part into several files without changing the bundle (the parts are joined in file-name order into one script).
  python tools/split_js.py FILE NEWNAME:LINE [NEWNAME:LINE ...] [--write]
FILE keeps the lines before the first LINE; every NEWNAME gets the lines from its LINE up to the next one. The names must sort between FILE and the
next existing part (e.g. 40-network.js -> 41-ignored.js, 42-flows.js). The joined bundle is compared before and after: if it differs by one byte,
the files are restored."""
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vedetta"))
from app import assets  # noqa: E402

args = [a for a in sys.argv[1:] if not a.startswith("--")]
write = "--write" in sys.argv
folder = ROOT / "vedetta" / "app" / "frontend" / "ha" / "js"
src = folder / args[0]
cuts = [(a.split(":")[0], int(a.split(":")[1])) for a in args[1:]]
text = src.read_text(encoding="utf-8")
lines = text.splitlines(keepends=True)
assert [c[1] for c in cuts] == sorted(c[1] for c in cuts) and cuts[0][1] > 1
bounds = [1] + [c[1] for c in cuts] + [len(lines) + 1]
chunks = [("".join(lines[bounds[i] - 1:bounds[i + 1] - 1])) for i in range(len(bounds) - 1)]
names = [src.name] + [c[0] for c in cuts]
before = hashlib.sha256(assets.bundle("ha/ha.js").encode()).hexdigest()
order = sorted(p.name for p in folder.glob("*.js") if p.name != src.name) + names
for a, b in zip(names, names[1:]):
    assert a < b, f"{b} must sort after {a}"
print(", ".join(f"{n}: {len(c.splitlines())} lines" for n, c in zip(names, chunks)))
if write:
    for n, c in zip(names, chunks):
        (folder / n).write_text(c, encoding="utf-8", newline="")
    assets._cache.clear() if hasattr(assets, "_cache") else None
    after = hashlib.sha256("".join(p.read_text(encoding="utf-8") for p in assets.parts("ha/ha.js")).encode()).hexdigest()
    if after != before:
        for n in names[1:]:
            (folder / n).unlink()
        src.write_text(text, encoding="utf-8", newline="")
        sys.exit("the bundle changed: restored")
    print("bundle identical:", before[:12])
