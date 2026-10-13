"""Reading order, top-down (the stepdown rule): in every module a private helper is written RIGHT BELOW the function that uses it, so a person reads the story first and the detail after.
Only a pure move: a helper is moved only if it is private (leading underscore), used by exactly one other function of the module, and not named anywhere else at module level
(decorators, default values, annotations, constants, classes), so nothing that runs when the module is loaded can see a different order. The text of every function is kept as it is
(with its decorators and the comment lines right above it); after the move the set of definitions is compared with the one before, and a module that does not match is left untouched.
    python tools/stepdown.py [APP_DIR] [--write]"""
import ast
import sys
from pathlib import Path

FUNC = (ast.FunctionDef, ast.AsyncFunctionDef)


def names_in(node) -> set:
    return {x.id for x in ast.walk(node) if isinstance(x, ast.Name)}


def module_level_names(tree: ast.Module) -> set:
    """Names that are read when the module is loaded (not inside a function body): decorators, default values, annotations, constants, class bodies."""
    out = set()
    for n in tree.body:
        if isinstance(n, FUNC):
            for d in n.decorator_list:
                out |= names_in(d)
            for d in n.args.defaults + [k for k in n.args.kw_defaults if k is not None]:
                out |= names_in(d)
            for a in n.args.args + n.args.posonlyargs + n.args.kwonlyargs + [x for x in (n.args.vararg, n.args.kwarg) if x]:
                if a.annotation is not None:
                    out |= names_in(a.annotation)
            if n.returns is not None:
                out |= names_in(n.returns)
        else:
            out |= names_in(n)
    return out


def reorder(text: str):
    tree = ast.parse(text)
    lines = text.split("\n")
    funcs = {n.name: n for n in tree.body if isinstance(n, FUNC)}
    loaded = module_level_names(tree)
    callers: dict = {}
    for name, fn in funcs.items():
        used = names_in(fn)
        for other in funcs:
            if other != name and other in used:
                callers.setdefault(other, set()).add(name)
    movable = {n for n in funcs if n.startswith("_") and not n.startswith("__") and len(callers.get(n, ())) == 1 and n not in loaded}
    helpers_of: dict = {}
    pos = {n.name: i for i, n in enumerate(tree.body) if isinstance(n, FUNC)}
    for n in movable:
        helpers_of.setdefault(next(iter(callers[n])), []).append(n)
    for k in helpers_of:
        helpers_of[k].sort(key=lambda nm: pos[nm])
    # segments: from the first non-blank line after the previous item (comments above an item travel with it) to the end of the item; the blank lines after it are its gap
    segs = []
    prev_end = 0
    for n in tree.body:
        start = min([n.lineno] + [d.lineno for d in getattr(n, "decorator_list", [])])
        first = prev_end + 1
        while first < start and lines[first - 1].strip() == "":
            first += 1
        segs.append({"node": n, "lines": lines[first - 1:n.end_lineno], "start": first, "end": n.end_lineno})
        prev_end = n.end_lineno
    if not segs:
        return text, 0
    for i, sg in enumerate(segs):
        nxt = segs[i + 1]["start"] if i + 1 < len(segs) else len(lines) + 1
        sg["gap"] = lines[sg["end"]:nxt - 1]
    tail = lines[segs[-1]["end"]:]
    segs[-1]["gap"] = []
    prologue = lines[:segs[0]["start"] - 1]
    seg_of = {sg["node"].name: sg for sg in segs if isinstance(sg["node"], FUNC)}
    order, emitted = [], set()

    def emit(sg):
        order.append(sg)
        emitted.add(id(sg))
        for h in helpers_of.get(getattr(sg["node"], "name", None), []):
            if id(seg_of[h]) not in emitted:
                emit(seg_of[h])

    for sg in segs:
        if isinstance(sg["node"], FUNC) and sg["node"].name in movable:
            continue
        emit(sg)
    is_def = lambda sg: isinstance(sg["node"], FUNC + (ast.ClassDef,))  # noqa: E731
    out = list(prologue)
    for k, sg in enumerate(order):
        out.extend(sg["lines"])
        if k + 1 < len(order):
            gap = list(sg["gap"])
            if (is_def(sg) or is_def(order[k + 1])) and len(gap) < 2:
                gap = ["", ""]
            out.extend(gap)
    out.extend(tail)
    return "\n".join(out), len(movable)


def signature(text: str):
    """The set of top-level definitions, order-free, to prove that only the order changed."""
    return sorted(ast.dump(n) for n in ast.parse(text).body)


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    root = Path(args[0]) if args else Path(__file__).resolve().parent.parent / "vedetta" / "app"
    write = "--write" in sys.argv
    moved = changed = refused = 0
    for f in sorted(root.rglob("*.py")):
        if "__pycache__" in f.parts or f.name == "__init__.py":
            continue
        raw = f.read_bytes().decode("utf-8")
        crlf = "\r\n" in raw
        text = raw.replace("\r\n", "\n")
        try:
            new, n = reorder(text)
            ok = n == 0 or new == text or signature(new) == signature(text)
        except Exception as exc:  # noqa: BLE001
            print("skip (cannot analyse)", f.name, repr(exc)[:80])
            refused += 1
            continue
        if n == 0 or new == text:
            continue
        if not ok:
            print("REFUSED (definitions differ after the move):", f.relative_to(root))
            refused += 1
            continue
        moved += n
        changed += 1
        print("%3d helpers moved in %s" % (n, f.relative_to(root)))
        if write:
            f.write_bytes((new.replace("\n", "\r\n") if crlf else new).encode("utf-8"))
    print("modules changed %d, helpers moved %d, refused %d%s" % (changed, moved, refused, "" if write else " (dry run: nothing written)"))
    print("DONE_STEPDOWN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
