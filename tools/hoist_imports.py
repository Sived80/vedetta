"""Move imports done inside functions up to the top of their module, where that cannot change anything.
  python tools/hoist_imports.py [--write] [--only app/path/file.py]
Moved: `from . import module` / `from ..pkg import module` / `import app.x` that import a MODULE (so what is used is read from it at call time: a module attribute
that a test or the program rebinds is still seen), when the module imported does not lead back to the importer through the imports already at the top of
the modules (a cycle) - judged one import after the other, each accepted one counting for the next. Not moved: a NAME imported from a module (`from x import history`:
the top-level name would keep the old object when something rebinds it), anything in a cycle, anything whose name is already used at module level, anything
in a statement with several names of which some stay. Without --write it only reports."""
import ast
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "vedetta"
APP = ROOT / "app"


def modname(path: Path) -> str:
    parts = list(path.relative_to(ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def resolve(cur: str, node: ast.ImportFrom, is_pkg: bool):
    if node.level == 0:
        return node.module if node.module and node.module.startswith("app") else None
    base = cur.split(".")
    if not is_pkg:
        base = base[:-1]
    base = base[: len(base) - (node.level - 1)]
    return ".".join(base + ([node.module] if node.module else []))


def main() -> None:
    write = "--write" in sys.argv
    only = next((sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--only"), None)
    mods = {modname(p): p for p in APP.rglob("*.py")}
    texts = {n: p.read_text(encoding="utf-8").replace("\r\n", "\n") for n, p in mods.items()}
    trees = {n: ast.parse(t) for n, t in texts.items()}
    top_edges = defaultdict(set)

    def targets(cur: str, node):
        """[(module imported, bound name)] when EVERY alias of the statement is a module; None otherwise."""
        is_pkg = mods[cur].name == "__init__.py"
        out = []
        if isinstance(node, ast.ImportFrom):
            base = resolve(cur, node, is_pkg)
            if base is None:
                return None
            for a in node.names:
                cand = f"{base}.{a.name}"
                if cand not in mods:
                    return None
                out.append((cand, a.asname or a.name))
        else:
            for a in node.names:
                if not a.name.startswith("app") or a.name not in mods:
                    return None
                out.append((a.name, a.asname or a.name.split(".")[0]))
        return out

    for name, tree in trees.items():
        for n in tree.body:
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                for tgt in (targets(name, n) or []):
                    top_edges[name].add(tgt[0])
                if isinstance(n, ast.ImportFrom):
                    base = resolve(name, n, mods[name].name == "__init__.py")
                    if base in mods:
                        top_edges[name].add(base)

    def reaches(src: str, dst: str) -> bool:
        seen, stack = set(), [src]
        while stack:
            cur = stack.pop()
            if cur == dst:
                return True
            if cur in seen:
                continue
            seen.add(cur)
            for nxt in top_edges.get(cur, ()):
                stack.append(nxt)
                parent = nxt.rsplit(".", 1)[0]
                if parent in mods:
                    stack.append(parent)
        return False

    plan = defaultdict(list)                   # module -> [(statement node, [(target, bound name)])]
    for name in sorted(mods):
        if only and mods[name].relative_to(ROOT).as_posix() != only:
            continue
        tree = trees[name]
        bound = {t.id for n in tree.body for t in ast.walk(n) if isinstance(t, ast.Name) and isinstance(t.ctx, ast.Store)}
        bound |= {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
        for n in tree.body:
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                bound |= {a.asname or a.name.split(".")[0] for a in n.names}
        taken_here = {}
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for n in fn.body:                  # only statements of the function body itself, not nested in an if or a try
                if not isinstance(n, (ast.Import, ast.ImportFrom)) or n.lineno != n.end_lineno:
                    continue
                tg = targets(name, n)
                if not tg:
                    continue
                if any(reaches(t, name) for t, _b in tg):
                    print(f"cycle   {name}:{n.lineno} -> {[t for t, _ in tg]}")
                    continue
                if any(b in bound and taken_here.get(b) != t for t, b in tg):
                    print(f"name in use   {name}:{n.lineno} -> {[b for _, b in tg]}")
                    continue
                for t, b in tg:
                    taken_here[b] = t
                    top_edges[name].add(t)
                plan[name].append((n, tg))
                print(f"hoist   {name}:{n.lineno} -> {[t for t, _ in tg]}")
    total = sum(len(v) for v in plan.values())
    print("statements to move:", total, "in", len(plan), "modules")
    if not write:
        return
    for name, items in plan.items():
        lines = texts[name].split("\n")
        tree = trees[name]
        new_top = []
        for n, _tg in items:
            stmt = lines[n.lineno - 1].split("#", 1)[0].strip()
            if stmt not in new_top and not any(stmt == lines[t.lineno - 1].strip() for t in tree.body if isinstance(t, (ast.Import, ast.ImportFrom)) and t.lineno == t.end_lineno):
                new_top.append(stmt)
        drop = set()
        for n, _tg in items:
            drop.add(n.lineno - 1)
            prev = n.lineno - 2
            if prev >= 0 and lines[prev].strip().startswith("#") and "import" in lines[prev]:
                drop.add(prev)                 # the comment that explained the late import
        last = max((t.end_lineno for t in tree.body if isinstance(t, (ast.Import, ast.ImportFrom))), default=0)
        out = []
        for i, line in enumerate(lines):
            if i not in drop:
                out.append(line)
            if i == last - 1:
                out.extend(new_top)
        text = "\n".join(out)
        try:
            ast.parse(text)
        except SyntaxError as exc:
            print("SKIPPED (the result does not parse)", name, exc)
            continue
        raw = mods[name].read_bytes().decode("utf-8")
        mods[name].write_bytes((text.replace("\n", "\r\n") if "\r\n" in raw else text).encode("utf-8"))
        print("written", name)


if __name__ == "__main__":
    main()
