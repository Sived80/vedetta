"""Move top-level functions / classes / constants of a module into a new sibling module, keeping the old one working.
  python tools/split_module.py FILE NEWNAME name1 name2 ...  [--write]
The moved code (with the comment lines right above it) goes to NEWNAME.py next to FILE. The old module gets `from .NEWNAME import ...` for
everything it still uses of what moved, and keeps exporting the moved names so `old.name` keeps working for the other modules and the tests.
The new module gets the imports it needs, copied from the old one. If the moved code needs a name that stays defined in the old module, the
tool stops and lists it: move that name too, or move it first to a module of its own. Without --write it only reports.
--router: the new module goes to the sub-package `routes/` next to FILE, the `@app.<verb>` decorators become `@router.<verb>`, relative imports get
one more dot, and FILE includes the new router (`app.include_router`) next to the other routers."""
import ast
import sys
from pathlib import Path

args = [a for a in sys.argv[1:] if not a.startswith("--")]
write = "--write" in sys.argv
router = "--router" in sys.argv
path, new, names = Path(args[0]), args[1], set(args[2:])
raw = path.read_bytes().decode("utf-8")
nl = "\r\n" if "\r\n" in raw else "\n"
src = raw.replace("\r\n", "\n")
lines = src.split("\n")
tree = ast.parse(src)


def target_names(t):
    """Names bound by an assignment target: `A = 1` -> [A]; `A, B = 1, 2` -> [A, B] (attributes and items bind no top-level name)."""
    if isinstance(t, ast.Name):
        return [t.id]
    if isinstance(t, (ast.Tuple, ast.List)):
        return [i for e in t.elts for i in target_names(e)]
    return []


def defined(n):
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [n.name]
    if isinstance(n, ast.Assign):
        return [i for t in n.targets for i in target_names(t)]
    if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
        return [n.target.id]
    return []


top = [n for n in tree.body]
all_defs = {d for n in top for d in defined(n)}
missing = names - all_defs
assert not missing, f"not found at top level: {sorted(missing)}"
imports = [n for n in top if isinstance(n, (ast.Import, ast.ImportFrom))]
import_names = {}
for n in imports:
    for a in n.names:
        import_names[(a.asname or a.name).split(".")[0]] = n


def first_line(n):
    a = min([n.lineno] + [d.lineno for d in getattr(n, "decorator_list", [])])
    while a - 2 >= 0 and lines[a - 2].lstrip().startswith("#"):
        a -= 1
    return a


moved = [n for n in top if set(defined(n)) & names]
for n in moved:
    assert set(defined(n)) <= names or isinstance(n, ast.Assign), f"{defined(n)} defined together with names not listed"
moved_defs = {d for n in moved for d in defined(n)}
stay = [n for n in top if n not in moved and n not in imports]
stay_defs = {d for n in stay for d in defined(n)}
def body_names(n):
    skip = {id(x) for d in getattr(n, "decorator_list", []) for x in ast.walk(d)} if router else set()    # `@app.get(...)` is rewritten, `app` stays behind
    return {x.id for x in ast.walk(n) if isinstance(x, ast.Name) and id(x) not in skip}


used_in_moved = {x for n in moved for x in body_names(n)}
needs_back = sorted((used_in_moved & stay_defs) - moved_defs)
if needs_back:
    print("the moved code needs names that stay in the old module (move them too, or first elsewhere):", needs_back)
    sys.exit(1)
used_in_stay = {x.id for n in stay for x in ast.walk(n) if isinstance(x, ast.Name)}
export = sorted(moved_defs)      # every moved name stays reachable as old.name (other modules and the tests use them)
# imports the new module needs
need_imp = []
for name in sorted(used_in_moved & set(import_names)):
    node = import_names[name]
    if node not in need_imp:
        need_imp.append(node)


def import_text(node):
    seg = "\n".join(lines[node.lineno - 1:node.end_lineno])
    if isinstance(node, ast.ImportFrom) and node.level == 0 or isinstance(node, ast.Import):
        return seg
    return seg      # relative imports stay valid: the new module is a sibling


# only the names actually used, per import statement
def trimmed(node):
    keep = [a for a in node.names if (a.asname or a.name).split(".")[0] in used_in_moved]
    if isinstance(node, ast.Import):
        return "import " + ", ".join(a.name + (f" as {a.asname}" if a.asname else "") for a in keep)
    mod = "." * node.level + (node.module or "")
    return f"from {mod} import " + ", ".join(a.name + (f" as {a.asname}" if a.asname else "") for a in keep)


body = []
for n in moved:
    body.append("\n".join(lines[first_line(n) - 1:n.end_lineno]))
doc = ast.get_docstring(tree)
import re
imp_text = "\n".join(trimmed(i) for i in need_imp)
body_text = "\n\n\n".join(body)
head = f'"""{new}: moved out of {path.stem}.py (see tools/split_module.py)."""\n'
if router:
    up = lambda s: re.sub(r"^([ \t]*)from (\.+)", lambda m: m.group(1) + "from " + m.group(2) + ".", s, flags=re.M)
    imp_text, body_text = up(imp_text), up(body_text)
    body_text = re.sub(r"^@app\.", "@router.", body_text, flags=re.M)
    imp_text = "from fastapi import APIRouter\n" + imp_text
    body_text = "router = APIRouter()\n\n\n" + body_text
newmod = head + imp_text + "\n\n\n" + body_text + "\n"
print(f"{len(moved)} items -> {new}.py ({sum(n.end_lineno - first_line(n) + 1 for n in moved)} lines); old module re-imports: {export}")
if write:
    cut = set()
    for n in moved:
        cut.update(range(first_line(n), n.end_lineno + 1))
    kept = [l for i, l in enumerate(lines, 1) if i not in cut]
    out = "\n".join(kept)
    # re-import after the last top-level import
    last_imp = max(i.end_lineno for i in imports)
    shift = sum(1 for i in cut if i <= last_imp)
    ol = out.split("\n")
    mod = f".routes.{new}" if router else f".{new}"
    ins = [f"from {mod} import {', '.join(export)}  # noqa: F401" if export else f"from . import {new}  # noqa: F401"]
    if router:
        ins.append(f"from .routes import {new} as routes_{new}")
    ol[last_imp - shift:last_imp - shift] = ins
    if router:
        idx = max(i for i, l in enumerate(ol) if l.startswith("app.include_router("))
        ol.insert(idx + 1, f"app.include_router(routes_{new}.router)")
    path.write_bytes("\n".join(ol).replace("\n", nl).encode("utf-8"))
    target = (path.parent / "routes" / f"{new}.py") if router else (path.parent / f"{new}.py")
    target.write_bytes(newmod.replace("\n", nl).encode("utf-8"))
    print("written")
