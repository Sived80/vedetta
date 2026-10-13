"""Two measures for reducing the code without making it cleverer:
  nested  - functions defined inside functions, and whether each one captures anything from the function around it (a nested function that captures nothing can be a plain function of the module;
            one that captures local state is a closure and stays where it is);
  clones  - blocks of code written more than once (the same N non-blank lines, comments and docstrings ignored). The Rule of Three decides: three copies or more are reported as worth a
            shared function, two copies are only counted (a wrong abstraction costs more than a copy).
Python only, read only.
    python tools/nested_and_clones.py [APP_DIR] [--window 6] [--list]"""
import ast
import builtins
import sys
from collections import defaultdict
from pathlib import Path

FUNC = (ast.FunctionDef, ast.AsyncFunctionDef)


def bound_names(fn):
    """Names that a function binds itself: parameters and assigned/loop/with/except/import names (not those of nested scopes)."""
    out = {a.arg for a in fn.args.args + fn.args.kwonlyargs + fn.args.posonlyargs}
    for a in (fn.args.vararg, fn.args.kwarg):
        if a:
            out.add(a.arg)
    stack = list(fn.body)
    while stack:
        n = stack.pop()
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            out.add(n.id)
        elif isinstance(n, FUNC + (ast.ClassDef,)):
            out.add(n.name)
            continue
        elif isinstance(n, ast.Lambda):
            continue
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            out |= {(a.asname or a.name).split(".")[0] for a in n.names}
        elif isinstance(n, ast.ExceptHandler) and n.name:
            out.add(n.name)
        stack.extend(ast.iter_child_nodes(n))
    return out


def loaded_names(fn):
    return {n.id for n in ast.walk(fn) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    root = Path(args[0]) if args else Path(__file__).resolve().parent.parent / "vedetta" / "app"
    window = int(sys.argv[sys.argv.index("--window") + 1]) if "--window" in sys.argv else 6
    show = "--list" in sys.argv
    free, closures = [], []
    windows = defaultdict(list)
    total_lines = 0
    for f in sorted(root.rglob("*.py")):
        if "__pycache__" in f.parts or f.name == "__init__.py":
            continue
        rel = f.relative_to(root).as_posix()
        text = f.read_text(encoding="utf-8")
        tree = ast.parse(text)
        for outer in ast.walk(tree):
            if not isinstance(outer, FUNC):
                continue
            outer_bound = bound_names(outer)
            for inner in [n for n in outer.body for n in ast.walk(n) if isinstance(n, FUNC)]:
                inner_bound = bound_names(inner)
                captured = sorted((loaded_names(inner) - inner_bound) & outer_bound - set(dir(builtins)))
                (closures if captured else free).append((rel, inner.lineno, outer.name, inner.name, captured))
        # clones: normalised code lines without docstrings and comments
        doc_lines = set()
        for n in ast.walk(tree):
            if isinstance(n, FUNC + (ast.ClassDef, ast.Module)) and n.body and isinstance(n.body[0], ast.Expr) and isinstance(getattr(n.body[0], "value", None), ast.Constant) and isinstance(n.body[0].value.value, str):
                doc_lines |= set(range(n.body[0].lineno, n.body[0].end_lineno + 1))
        lines = [(i + 1, " ".join(l.split())) for i, l in enumerate(text.splitlines()) if l.strip() and not l.strip().startswith("#") and (i + 1) not in doc_lines]
        total_lines += len(lines)
        for k in range(len(lines) - window + 1):
            chunk = lines[k:k + window]
            if all(len(c[1]) <= 3 or c[1] in ("else:", "try:", "return", "pass", "break", "continue") or c[1].startswith(("import ", "from ")) for c in chunk):
                continue
            windows["\n".join(c[1] for c in chunk)].append((rel, chunk[0][0]))
    repeated = {k: v for k, v in windows.items() if len({(r, l // window) for r, l in v}) >= 2}
    # merge overlapping windows of the same group into blocks
    groups3 = [v for v in repeated.values() if len(v) >= 3]
    groups2 = [v for v in repeated.values() if len(v) == 2]
    print("nested functions: %d | capture nothing (can be plain functions): %d | closures over local state: %d" % (len(free) + len(closures), len(free), len(closures)))
    print("code lines counted (no blank, comment or docstring): %d" % total_lines)
    print("blocks of %d lines written 3+ times: %d windows | exactly twice: %d windows" % (window, len(groups3), len(groups2)))
    if show:
        for rel, line, outer, inner, cap in free:
            print("  captures nothing: %s:%d %s > %s" % (rel, line, outer, inner))
        for rel, line, outer, inner, cap in closures[:12]:
            print("  closure:          %s:%d %s > %s uses %s" % (rel, line, outer, inner, ",".join(cap)[:60]))
        shown = set()
        for key, v in sorted(repeated.items(), key=lambda kv: -len(kv[1])):
            first = tuple(sorted(set(v))[:3])
            if len(v) >= 3 and first not in shown:
                shown.add(first)
                print("  x%d: %s" % (len(v), ", ".join("%s:%d" % x for x in sorted(set(v))[:4])))
                if len(shown) >= 10:
                    break
    print("DONE_NESTED_CLONES")
    return 0


if __name__ == "__main__":
    sys.exit(main())
