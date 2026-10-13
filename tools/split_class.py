"""Move methods of a class into a mixin class in a new sibling module; the original class inherits from the mixin, so nothing else changes.
  python tools/split_class.py FILE CLASS NEWMODULE MixinName method1 method2 ... [--write]
The mixin keeps the methods as they are (same `self` attributes). The module-level names the methods use (imports, helpers, constants) are
imported into the new module: imports are copied, and names defined in FILE that stay behind stop the tool (move them first). Use it to split a
class by topic; a later step can turn a mixin into a real collaborator if it deserves one."""
import ast
import sys
from pathlib import Path

args = [a for a in sys.argv[1:] if not a.startswith("--")]
write = "--write" in sys.argv
path, cls, new, mixin, names = Path(args[0]), args[1], args[2], args[3], set(args[4:])
raw = path.read_bytes().decode("utf-8")
nl = "\r\n" if "\r\n" in raw else "\n"
src = raw.replace("\r\n", "\n")
lines = src.split("\n")
tree = ast.parse(src)
klass = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
methods = {m.name: m for m in klass.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))}
consts = {n for n in names if n not in methods}        # module-level constants (Assign) listed among the names move with the methods
names = names - consts
missing = names - set(methods)
assert not missing, f"no such method: {sorted(missing)}"
imports = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
import_names = {}
for n in imports:
    for a in n.names:
        import_names[(a.asname or a.name).split(".")[0]] = n
top_defs = {}
for n in tree.body:
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        top_defs[n.name] = n
    elif isinstance(n, ast.Assign):
        for t in n.targets:
            if isinstance(t, ast.Name):
                top_defs[t.id] = n


def start(m):
    a = min([m.lineno] + [d.lineno for d in m.decorator_list])
    while a - 2 >= 0 and lines[a - 2].lstrip().startswith("#"):
        a -= 1
    return a


moved = [methods[k] for k in methods if k in names]
const_nodes = [n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(x, ast.Name) and x.id in consts for x in n.targets)]
assert len(const_nodes) == len(consts), f"constants not found at top level: {sorted(consts)}"
used = {x.id for m in moved for x in ast.walk(m) if isinstance(x, ast.Name)}
stay = sorted(u for u in used if u in top_defs and u != cls and u not in consts)
if stay:
    print("the moved methods use module-level names defined in the old file (move them to a module first):", stay)
    sys.exit(1)
need = []
for name in sorted(used & set(import_names)):
    if import_names[name] not in need:
        need.append(import_names[name])


def trimmed(node):
    keep = [a for a in node.names if (a.asname or a.name).split(".")[0] in used]
    if isinstance(node, ast.Import):
        return "import " + ", ".join(a.name + (f" as {a.asname}" if a.asname else "") for a in keep)
    return f"from {'.' * node.level}{node.module or ''} import " + ", ".join(a.name + (f" as {a.asname}" if a.asname else "") for a in keep)


body = "\n\n".join("\n".join(lines[start(m) - 1:m.end_lineno]) for m in moved)
const_text = "\n".join("\n".join(lines[c.lineno - 1:c.end_lineno]) for c in const_nodes)
newmod = f'"""{mixin}: methods of {cls} that belong together (moved out of {path.stem}.py by tools/split_class.py)."""\n' + \
    "\n".join(trimmed(i) for i in need) + ("\n\n" + const_text if const_text else "") + f"\n\n\nclass {mixin}:\n" + body + "\n"
print(f"{len(moved)} methods -> {new}.py ({sum(m.end_lineno - start(m) + 1 for m in moved)} lines), class {cls}({mixin})")
if write:
    cut = set()
    for m in moved:
        cut.update(range(start(m), m.end_lineno + 1))
    for c in const_nodes:
        cut.update(range(c.lineno, c.end_lineno + 1))
    kept = [l for i, l in enumerate(lines, 1) if i not in cut]
    out = "\n".join(kept)
    out = out.replace(f"class {cls}:", f"class {cls}({mixin}):", 1) if f"class {cls}:" in out else out.replace(f"class {cls}(", f"class {cls}({mixin}, ", 1)
    last_imp = max(i.end_lineno for i in imports)
    shift = sum(1 for i in cut if i <= last_imp)
    ol = out.split("\n")
    ol.insert(last_imp - shift, f"from .{new} import {', '.join([mixin] + sorted(consts))}")
    path.write_bytes("\n".join(ol).replace("\n", nl).encode("utf-8"))
    (path.parent / f"{new}.py").write_bytes(newmod.replace("\n", nl).encode("utf-8"))
    print("written")
