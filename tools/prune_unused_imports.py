"""Removes the imports that ruff reports as unused (F401) ONLY when nothing else in the repository reaches the module through that name: a name that other code imports from the module
(`from app.x import name`), reads as an attribute (`x.name`, also through an alias such as `state_mod.name`) or that a test replaces on the module is a re-export on purpose and stays.
Only the import statements at the top level of a module are rewritten, as a whole (the names that stay are written back; a statement left empty is deleted).
    python tools/prune_unused_imports.py [APP_DIR] [--write]"""
import ast
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
APP = REPO / "vedetta" / "app"


def used_names_by_module() -> dict:
    """{module stem: {names reached from outside}}: names imported from it, and attributes read or set on it (also through an alias)."""
    reached = defaultdict(set)
    stems = {f.stem for f in APP.rglob("*.py") if "__pycache__" not in f.parts}
    files = [f for base in (REPO / "vedetta", REPO / "tests", REPO / "tools") for f in base.rglob("*.py") if "__pycache__" not in f.parts]
    for f in files:
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        alias = {}
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom):
                mod = (n.module or "").split(".")[-1]
                if mod in stems:
                    for a in n.names:
                        reached[mod].add(a.name)
                for a in n.names:
                    if a.name in stems:
                        alias[a.asname or a.name] = a.name
            elif isinstance(n, ast.Import):
                for a in n.names:
                    last = a.name.split(".")[-1]
                    if last in stems:
                        alias[a.asname or last] = last
        for n in ast.walk(tree):
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name):
                stem = alias.get(n.value.id) or (n.value.id if n.value.id in stems else None)
                if stem:
                    reached[stem].add(n.attr)
            elif isinstance(n, ast.Attribute) and isinstance(n.value, ast.Attribute) and isinstance(n.value.value, ast.Name):
                stem = n.value.attr                                              # app.module.name
                if stem in stems:
                    reached[stem].add(n.attr)
    return reached


def rewrite(path: Path, names: set) -> None:
    raw = path.read_bytes().decode("utf-8")
    crlf = "\r\n" in raw
    text = raw.replace("\r\n", "\n")
    lines = text.split("\n")
    edits = []
    for node in ast.parse(text).body:
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        keep = [al for al in node.names if (al.asname or al.name).split(".")[-1] not in names]
        if len(keep) == len(node.names):
            continue
        if not keep:
            edits.append((node.lineno, node.end_lineno, []))
            continue
        items = [al.name + (" as " + al.asname if al.asname else "") for al in keep]
        head = ("from " + "." * node.level + (node.module or "") + " import ") if isinstance(node, ast.ImportFrom) else "import "
        line = head + ", ".join(items)
        if len(line) > 150 and isinstance(node, ast.ImportFrom):
            line = head + "(" + ", ".join(items) + ")"
        edits.append((node.lineno, node.end_lineno, [line]))
    for first, last, new_lines in sorted(edits, reverse=True):
        lines[first - 1:last] = new_lines
    out = "\n".join(lines)
    ast.parse(out)
    path.write_bytes((out.replace("\n", "\r\n") if crlf else out).encode("utf-8"))


def main() -> int:
    write = "--write" in sys.argv
    out = subprocess.run([sys.executable, "-m", "ruff", "check", str(APP), "--select", "F401", "--output-format", "json", "--exit-zero"], capture_output=True, text=True, cwd=REPO).stdout
    items = json.loads(out or "[]")
    reached = used_names_by_module()
    keep, drop = [], defaultdict(list)
    for it in items:
        path = Path(it["filename"])
        name = it["message"].split("`")[1].split(".")[-1]                      # `pkg.name` imported but unused
        if name in reached.get(path.stem, set()) or path.name == "__init__.py":
            keep.append((path.name, name))
        else:
            drop[path].append(it)
    for path, its in drop.items():
        print("remove %2d in %s: %s" % (len(its), path.relative_to(APP).as_posix(), ", ".join(i["message"].split("`")[1].split(".")[-1] for i in its)))
    print("unused imports reported: %d | removable: %d | kept (reached from outside, re-exports on purpose): %d" % (len(items), sum(len(v) for v in drop.values()), len(keep)))
    if write:
        for path, its in drop.items():
            rewrite(path, {i["message"].split("`")[1].split(".")[-1] for i in its})
    print("DONE_PRUNE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
