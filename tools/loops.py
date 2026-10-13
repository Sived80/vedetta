"""Inventory of the loops of the application, to check that each one ends and to see which ones can cost time:
  - `while` loops: unconditional (`while True`) or conditioned, whether the body can leave (break / return / raise), whether it waits (`await`) so that a cancel can stop it;
  - `for` loops nested two or more deep (the cost grows with the product of the sizes) and loops that touch the disk, the database or the network on every turn;
  - `while` loops whose condition is not changed in the body (the usual way to loop forever by mistake).
It reads the code only (no run), so it points at places to look at; it proves nothing by itself.
    python tools/loops.py [APP_DIR] [--list]"""
import ast
import sys
from collections import Counter
from pathlib import Path

FUNC = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
IO_CALLS = ("execute", "executemany", "open", "read_text", "write_text", "load_devices", "history", "httpx", "socket", "to_thread", "run_in_executor", "stat")


def walk_same_scope(node):
    """The nodes inside `node` without going into nested functions."""
    stack = list(ast.iter_child_nodes(node))
    while stack:
        n = stack.pop()
        yield n
        if not isinstance(n, FUNC):
            stack.extend(ast.iter_child_nodes(n))


def names_assigned(body_nodes):
    out = set()
    for stmt in body_nodes:
        for n in [stmt, *walk_same_scope(stmt)]:
            if isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                targets = n.targets if isinstance(n, ast.Assign) else [n.target]
                for t in targets:
                    out |= {x.id for x in ast.walk(t) if isinstance(x, ast.Name)} | {x.attr for x in ast.walk(t) if isinstance(x, ast.Attribute)}
            elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
                if isinstance(n.func.value, ast.Name):
                    out.add(n.func.value.id)                        # a method called on a name may change it (list.pop, queue.get...)
                elif isinstance(n.func.value, ast.Attribute):
                    out.add(n.func.value.attr)
            elif isinstance(n, ast.NamedExpr):
                out.add(n.target.id)
    return out


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    root = Path(args[0]) if args else Path(__file__).resolve().parent.parent / "vedetta" / "app"
    show = "--list" in sys.argv
    stats = Counter()
    rows = []
    for f in sorted(root.rglob("*.py")):
        if "__pycache__" in f.parts or f.name == "__init__.py":
            continue
        tree = ast.parse(f.read_text(encoding="utf-8"))
        rel = f.relative_to(root).as_posix()
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.AsyncFunctionDef) and not isinstance(fn, ast.FunctionDef):
                continue
            for n in walk_same_scope(fn):
                if isinstance(n, ast.While):
                    stats["while"] += 1
                    inner = [x for s in n.body for x in [s, *walk_same_scope(s)]]
                    can_leave = any(isinstance(x, (ast.Break, ast.Return, ast.Raise)) for x in inner)
                    waits = any(isinstance(x, (ast.Await, ast.AsyncFor, ast.AsyncWith)) for x in inner)
                    forever = isinstance(n.test, ast.Constant) and bool(n.test.value)
                    if forever:
                        stats["while True"] += 1
                        if not can_leave:
                            stats["while True without break/return/raise"] += 1
                            rows.append(("loop forever (ends only by cancel or exception)", rel, n.lineno, fn.name, "awaits" if waits else "NEVER AWAITS: a cancel cannot stop it"))
                        if isinstance(fn, ast.AsyncFunctionDef) and not waits:
                            stats["async while True that never awaits"] += 1
                            rows.append(("async loop that never awaits", rel, n.lineno, fn.name, ""))
                    else:
                        cond_names = {x.id for x in ast.walk(n.test) if isinstance(x, ast.Name)} | {x.attr for x in ast.walk(n.test) if isinstance(x, ast.Attribute)}
                        changed = names_assigned(n.body)
                        if not (cond_names & changed) and not can_leave:
                            stats["while: the condition is not changed in the body and nothing leaves"] += 1
                            rows.append(("while whose condition does not change", rel, n.lineno, fn.name, ast.unparse(n.test)[:60]))
                elif isinstance(n, (ast.For, ast.AsyncFor)):
                    stats["for"] += 1
                    nested = [x for s in n.body for x in [s, *walk_same_scope(s)] if isinstance(x, (ast.For, ast.AsyncFor, ast.While))]
                    if nested:
                        stats["for with a loop inside"] += 1
                        depth3 = any(isinstance(y, (ast.For, ast.While)) for x in nested for y in walk_same_scope(x))
                        if depth3:
                            stats["loops three deep"] += 1
                            rows.append(("three loops deep", rel, n.lineno, fn.name, ""))
                        else:
                            rows.append(("two loops deep", rel, n.lineno, fn.name, ast.unparse(n.iter)[:50]))
                    io = {c.func.attr if isinstance(c.func, ast.Attribute) else getattr(c.func, "id", "") for s in n.body for c in [s, *walk_same_scope(s)] if isinstance(c, ast.Call)}
                    hit = sorted(io & set(IO_CALLS))
                    if hit:
                        stats["for that touches disk/database/network on every turn"] += 1
                        rows.append(("loop with I/O in the body", rel, n.lineno, fn.name, ",".join(hit)))
    print("while loops: %d | for loops: %d" % (stats["while"], stats["for"]))
    for k in ("while True", "while True without break/return/raise", "async while True that never awaits", "while: the condition is not changed in the body and nothing leaves", "for with a loop inside",
              "loops three deep", "for that touches disk/database/network on every turn"):
        print("  %-72s %d" % (k, stats[k]))
    by_kind = Counter(r[0] for r in rows)
    print("flagged places by kind:", dict(by_kind))
    if show:
        for kind, rel, line, fn, note in sorted(rows):
            print("  %-48s %s:%d %s %s" % (kind, rel, line, fn, note))
    print("DONE_LOOPS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
