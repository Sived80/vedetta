"""Which loops could be written more simply? A static count of the loop shapes that have a plainer form (Fowler, "Replace Loop with Pipeline"; PEP 20, flat is better than nested):
  collect   - `out = []` then a loop that only appends (optionally under an `if`)                       -> a comprehension
  find      - a loop whose body is `if cond: return X` followed by a plain return                       -> any() / next()
  dict      - `d = {}` then a loop that only sets d[key] = value                                       -> a dict comprehension
  count     - a counter incremented in the loop (`n += 1` under an if)                                  -> sum(1 for ...)
  nested    - a loop inside a loop (a generator for the inner one often makes it flat)
  skeleton  - the same loop shape written several times in the code (the shape is the same when the names are ignored)
It reads the code only; it points at places to look at, the decision is made loop by loop.
    python tools/loop_patterns.py [APP_DIR] [--list]"""
import ast
import sys
from collections import Counter, defaultdict
from pathlib import Path

FUNC = (ast.FunctionDef, ast.AsyncFunctionDef)


def only_appends(loop, name):
    """The body of the loop is `name.append(...)`, possibly under ifs (no else)."""
    body = loop.body
    while len(body) == 1 and isinstance(body[0], ast.If) and not body[0].orelse:
        body = body[0].body
    return (len(body) == 1 and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Call) and isinstance(body[0].value.func, ast.Attribute)
            and body[0].value.func.attr == "append" and isinstance(body[0].value.func.value, ast.Name) and body[0].value.func.value.id == name)


def only_sets(loop, name):
    body = loop.body
    while len(body) == 1 and isinstance(body[0], ast.If) and not body[0].orelse:
        body = body[0].body
    return len(body) == 1 and isinstance(body[0], ast.Assign) and isinstance(body[0].targets[0], ast.Subscript) and isinstance(body[0].targets[0].value, ast.Name) and body[0].targets[0].value.id == name


class Skeleton(ast.NodeTransformer):
    """The loop with every name, constant and attribute made anonymous: two loops with the same shape give the same text."""
    def visit_Name(self, node):
        return ast.copy_location(ast.Name(id="_", ctx=node.ctx), node)

    def visit_Constant(self, node):
        return ast.copy_location(ast.Constant(value=0), node)

    def visit_JoinedStr(self, node):
        return ast.copy_location(ast.Constant(value=0), node)

    def visit_Attribute(self, node):
        self.generic_visit(node)
        node.attr = "_"
        return node


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    root = Path(args[0]) if args else Path(__file__).resolve().parent.parent / "vedetta" / "app"
    stats, rows, shapes = Counter(), [], defaultdict(list)
    for f in sorted(root.rglob("*.py")):
        if "__pycache__" in f.parts or f.name == "__init__.py":
            continue
        rel = f.relative_to(root).as_posix()
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, FUNC):
                continue
            body = fn.body
            for i, stmt in enumerate(body):
                if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name) and i + 1 < len(body) and isinstance(body[i + 1], (ast.For, ast.AsyncFor)):
                    name, nxt = stmt.targets[0].id, body[i + 1]
                    if isinstance(stmt.value, ast.List) and not stmt.value.elts and only_appends(nxt, name):
                        stats["collect"] += 1
                        rows.append(("collect -> comprehension", rel, nxt.lineno, fn.name))
                    elif isinstance(stmt.value, ast.Dict) and not stmt.value.keys and only_sets(nxt, name):
                        stats["dict"] += 1
                        rows.append(("dict -> dict comprehension", rel, nxt.lineno, fn.name))
            for n in ast.walk(fn):
                if isinstance(n, (ast.For, ast.AsyncFor)):
                    inner = n.body
                    if len(inner) == 1 and isinstance(inner[0], ast.If) and not inner[0].orelse and len(inner[0].body) == 1 and isinstance(inner[0].body[0], ast.Return):
                        stats["find"] += 1
                        rows.append(("find -> any()/next()", rel, n.lineno, fn.name))
                    if any(isinstance(s, ast.AugAssign) and isinstance(s.op, ast.Add) and isinstance(s.value, ast.Constant) and s.value.value == 1 for x in inner for s in ast.walk(x)):
                        stats["count"] += 1
                        rows.append(("count -> sum(1 for ...)", rel, n.lineno, fn.name))
                    if any(isinstance(s, (ast.For, ast.While)) for x in inner for s in ast.walk(x)):
                        stats["nested"] += 1
                    shape = ast.unparse(Skeleton().visit(ast.parse(ast.unparse(n)).body[0]))
                    if shape.count("\n") >= 3:
                        shapes[shape].append((rel, n.lineno, fn.name))
    repeated = {k: v for k, v in shapes.items() if len(v) >= 3}
    stats["skeleton (a shape written 3+ times)"] = len(repeated)
    print("loops that have a plainer form: collect %d | find %d | dict %d | count %d | nested %d | shapes written 3+ times: %d (%d places)" % (
        stats["collect"], stats["find"], stats["dict"], stats["count"], stats["nested"], len(repeated), sum(len(v) for v in repeated.values())))
    if "--list" in sys.argv:
        for kind, rel, line, fn in sorted(rows):
            print("  %-28s %s:%d %s" % (kind, rel, line, fn))
        for shape, where in sorted(repeated.items(), key=lambda kv: -len(kv[1]))[:8]:
            print("  same shape x%d: %s" % (len(where), ", ".join("%s:%d" % (r, ln) for r, ln, _ in where[:5])))
            print("      " + shape.replace("\n", "\n      ")[:300])
    print("DONE_PATTERNS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
