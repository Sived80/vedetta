"""The structure of vedetta/app: every module imports, no import cycle at module level, and each package only reaches where it should.

Packages (see docs/DEVELOPMENT.md): scan, recognition, ha, export, storage, routes; the root keeps the core (state, i18n, paths...).
Rules checked here:
- every module under app/ can be imported;
- no cycle between modules through imports at the top of a file (an import inside a function is how the few mutual
  dependencies of scan, recognition and ha are kept apart; they are listed in LATE_OK and must not grow);
- `routes` is only used by main (a route is the outermost layer: nothing else imports it);
- `export` does not import `routes`."""
import ast
import importlib
import os
import pkgutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "vedetta"
sys.path.insert(0, str(ROOT))
import app  # noqa: E402

# every folder with Python files is a package (walk_packages would silently skip one without __init__.py)
for d in sorted({f.parent for f in (ROOT / "app").rglob("*.py") if "__pycache__" not in f.parts}):
    assert (d / "__init__.py").exists(), "no __init__.py in %s" % d.relative_to(ROOT)

names = [m.name for m in pkgutil.walk_packages(app.__path__, "app.")]
packages = {m.name for m in pkgutil.walk_packages(app.__path__, "app.") if m.ispkg}   # a package is not a module to depend on: its files are
for n in names:
    importlib.import_module(n)      # raises if a module cannot be imported


def deps(path: Path, module: str, top_only: bool) -> set[str]:
    """Dotted names of the app modules a file imports (resolved to modules, packages left out)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    pkg = module.split(".") if path.name == "__init__.py" else module.split(".")[:-1]
    out: set[str] = set()

    def visit(node, in_func):
        for ch in ast.iter_child_nodes(node):
            f = in_func or isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef))
            if isinstance(ch, ast.ImportFrom) and not (top_only and f):
                base = pkg[: len(pkg) - (ch.level - 1)] if ch.level else []
                mod = ".".join(base + ([ch.module] if ch.module else [])) if ch.level else (ch.module or "")
                if mod == "app" or mod.startswith("app."):
                    for a in ch.names:
                        out.add(f"{mod}.{a.name}")
                    out.add(mod)
            visit(ch, f)
    visit(tree, False)
    return {d for d in out if d in names}


def graph(top_only: bool) -> dict[str, set[str]]:
    g = {}
    for n in names:
        p = ROOT / (n.replace(".", "/") + ".py")
        if not p.exists():
            p = ROOT / n.replace(".", "/") / "__init__.py"
        g[n] = {d for d in deps(p, n, top_only) if d != n and not n.startswith(d + ".") and d not in packages}
    return g


def cycles(g):
    index, low, stack, on, out, c = {}, {}, [], set(), [], [0]
    sys.setrecursionlimit(10000)

    def sc(v):
        index[v] = low[v] = c[0]; c[0] += 1; stack.append(v); on.add(v)
        for w in g.get(v, ()):
            if w not in index:
                sc(w); low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop(); on.discard(w); comp.append(w)
                if w == v:
                    break
            if len(comp) > 1:
                out.append(sorted(comp))
    for v in sorted(g):
        if v not in index:
            sc(v)
    return out


top = graph(True)
assert not cycles(top), "import cycle at module level: %s" % cycles(top)

# the late imports that exist today (inside functions): they must not grow without a reason written here
full = graph(False)
late = {n: sorted(full[n] - top[n]) for n in names if full[n] - top[n]}
LATE_OK = 44        # measured when the modules were put in packages
count = sum(len(v) for v in late.values())
assert count <= LATE_OK, "more imports inside functions than before (%d > %d): %s" % (count, LATE_OK, late)

# routes are the outermost layer; export does not reach into routes
for n, d in full.items():
    if n.startswith("app.routes") or n == "app.routes":
        continue
    bad = [x for x in d if x.startswith("app.routes")]
    assert not bad or n == "app.main", "%s imports a route module: %s" % (n, bad)

# every `from app... import name` (also inside functions) names something that exists
unresolved = []
for n in names:
    p = ROOT / (n.replace(".", "/") + ".py")
    if not p.exists():
        p = ROOT / n.replace(".", "/") / "__init__.py"
    pkg = n.split(".") if p.name == "__init__.py" else n.split(".")[:-1]
    for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and (node.level or (node.module or "").startswith("app")):
            base = pkg[: len(pkg) - (node.level - 1)] if node.level else []
            mod = ".".join(base + ([node.module] if node.module else [])) if node.level else node.module
            try:
                m = importlib.import_module(mod)
            except ImportError as e:
                unresolved.append("%s: %s (%s)" % (n, mod, e)); continue
            for a in node.names:
                if a.name != "*" and not hasattr(m, a.name):
                    try:
                        importlib.import_module(mod + "." + a.name)
                    except ImportError:
                        unresolved.append("%s: %s.%s" % (n, mod, a.name))
assert not unresolved, "imports that point at nothing: " + "; ".join(unresolved)

print("ok: %d modules import, no cycle at module level, %d imports inside functions" % (len(names), count))
print("TUTTO OK")
