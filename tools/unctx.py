"""Take the `ctx` container out of a function that tools/split_function.py cut into steps (the inverse of that tool), mechanically.
  python tools/unctx.py FILE PARENT [--write]
PARENT must look like what the splitter writes:   ctx = SimpleNamespace(a=a, b=b)  followed only by calls  step(ctx) / await step(ctx), the last one returned.
Every attribute `ctx.x` becomes a plain variable `x`: a step gets the variables it reads as parameters and returns the ones a later step reads;
PARENT keeps them as local variables and passes them on. Comments and layout of the steps are kept (the text is edited in place, not regenerated).
Refused, with the reason, and nothing written: a step that can leave early (return inside a step that is not the last), `ctx` used as a whole (passed on,
getattr...), a nested function that assigns `ctx.x`, a variable that would clash with another name used in the same step, a read of something no earlier step set.
Without --write it only reports."""
import ast
import sys
from pathlib import Path


class Refuse(Exception):
    pass


def _attrs(step: ast.AST):
    """[(node, name, mode)] of every ctx.NAME in a step; mode is 'r', 'w' or 'rw' (augmented assignment); refuses any other use of ctx."""
    parents = {}
    for n in ast.walk(step):
        for c in ast.iter_child_nodes(n):
            parents[c] = n
    inner = [n for n in ast.walk(step) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)) and n is not step]
    out = []
    for n in ast.walk(step):
        if isinstance(n, ast.Name) and n.id == "ctx":
            par = parents.get(n)
            if not (isinstance(par, ast.Attribute) and par.value is n):
                raise Refuse(f"{step.name}: `ctx` is used as a whole (line {n.lineno})")
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "ctx":
            if isinstance(n.ctx, ast.Del):
                raise Refuse(f"{step.name}: del ctx.{n.attr}")
            mode = "r" if isinstance(n.ctx, ast.Load) else ("rw" if isinstance(parents.get(n), ast.AugAssign) else "w")
            if mode != "r" and any(n in ast.walk(f) for f in inner):
                raise Refuse(f"{step.name}: a nested function assigns ctx.{n.attr}")
            if n.lineno != n.end_lineno:
                raise Refuse(f"{step.name}: ctx.{n.attr} spans several lines")
            out.append((n, n.attr, mode))
    return out


def _own_nodes(node: ast.AST):
    """The nodes of a statement, without entering nested functions."""
    yield node
    for c in ast.iter_child_nodes(node):
        if not isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            yield from _own_nodes(c)


def _is_early_check(s: ast.AST) -> bool:
    """if _result is not None: return _result"""
    return (isinstance(s, ast.If) and not s.orelse and len(s.body) == 1 and isinstance(s.body[0], ast.Return)
            and getattr(s.body[0].value, "id", "") == "_result" and isinstance(s.test, ast.Compare) and len(s.test.ops) == 1
            and isinstance(s.test.ops[0], ast.IsNot) and getattr(s.test.left, "id", "") == "_result"
            and isinstance(s.test.comparators[0], ast.Constant) and s.test.comparators[0].value is None)


def _always_set(fn: ast.AST) -> set:
    """The ctx attributes a step assigns in a statement of its own body (not under an if, a loop, a try...): they are set whatever the path."""
    names = set()
    for s in fn.body:
        if isinstance(s, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            for n in ast.walk(s):
                if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "ctx" and isinstance(n.ctx, ast.Store):
                    names.add(n.attr)
    return names


def _plan(tree: ast.Module, parent_name: str):
    funcs = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    parent = funcs[parent_name]
    body = [s for s in parent.body if not (isinstance(s, ast.Expr) and isinstance(getattr(s, "value", None), ast.Constant))]
    head = body[0]
    if not (isinstance(head, ast.Assign) and len(head.targets) == 1 and getattr(head.targets[0], "id", "") == "ctx"
            and isinstance(head.value, ast.Call) and getattr(head.value.func, "id", "") == "SimpleNamespace" and not head.value.args):
        raise Refuse(f"{parent_name}: does not start with ctx = SimpleNamespace(...)")
    init = [(k.arg, k.value) for k in head.value.keywords]
    names = [k for k, _ in init]
    for i, (k, v) in enumerate(init):          # all the values are read before any is set: an assignment must not change what a later one reads
        if not (isinstance(v, ast.Name) and v.id == k) and any(isinstance(m, ast.Name) and m.id == k for _, w in init[i + 1:] for m in ast.walk(w)):
            raise Refuse(f"{parent_name}: initial value order matters for {k}")
    calls = []
    rest = body[1:]
    k = 0
    while k < len(rest):
        s = rest[k]
        early = False
        if (isinstance(s, ast.Assign) and len(s.targets) == 1 and getattr(s.targets[0], "id", "") == "_result"
                and k + 1 < len(rest) and _is_early_check(rest[k + 1])):
            early, call, k = True, s.value, k + 1                  # _result = step(ctx); if _result is not None: return _result
        else:
            call = s.value if isinstance(s, (ast.Expr, ast.Return)) else None
        last = k == len(rest) - 1
        awaited = isinstance(call, ast.Await)
        call = call.value if awaited else call
        ok = isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and len(call.args) == 1 and getattr(call.args[0], "id", "") == "ctx" and not call.keywords
        if not ok or (isinstance(s, ast.Return) and not last) or (early and last):
            raise Refuse(f"{parent_name}: line {s.lineno} is not a plain step call (a statement between steps)")
        calls.append((call.func.id, awaited, isinstance(s, ast.Return), early))
        k += 1
    # a name that a step also uses for something else gets a trailing underscore in every step: renaming a local variable never changes what it does
    renamed = set()
    for name, *_rest in calls:
        fn = funcs.get(name)
        if fn is not None and [a.arg for a in fn.args.args] == ["ctx"]:
            local_names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)} | {a.arg for n in ast.walk(fn) for a in getattr(getattr(n, "args", None), "args", [])} - {"ctx"}
            renamed |= {a for _, a, _m in _attrs(fn)} & local_names
    taken = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    for a in renamed:
        if a + "_" in taken:
            raise Refuse(f"{a}: would clash with a variable of the same name in a step, and {a}_ is already used")
    steps = []
    avail = list(names)
    for name, awaited, returned, early in calls:
        fn = funcs.get(name)
        if fn is None or [a.arg for a in fn.args.args] != ["ctx"]:
            raise Refuse(f"{name}: not a module-level function taking only ctx")
        uses = _attrs(fn)
        reads = [a for _, a, m in uses if "r" in m]
        writes = [a for _, a, m in uses if "w" in m]
        for a in reads:
            if a not in avail and a not in writes:
                raise Refuse(f"{name}: reads ctx.{a}, which no earlier step sets")
        always = _always_set(fn)
        # a value set only on some paths keeps what an earlier step gave it on the others: it has to come in as a parameter too
        params = list(dict.fromkeys([a for a in reads if a in avail] + [w for w in writes if w in avail and w not in always]))
        steps.append({"fn": fn, "awaited": awaited, "returned": returned, "early": early, "uses": uses, "params": params, "writes": list(dict.fromkeys(writes))})
        avail += [w for w in steps[-1]["writes"] if w not in avail]
    for i, st in enumerate(steps):
        later = {a for s in steps[i + 1:] for a in s["params"]}
        st["outs"] = [w for w in st["writes"] if w in later]
        st["maybe_unset"] = [w for w in st["outs"] if w not in _always_set(st["fn"]) and w not in st["params"]]
        rets = [n for s in st["fn"].body for n in _own_nodes(s) if isinstance(n, ast.Return)]
        st["returns"] = rets
        if i < len(steps) - 1 and rets and not st["early"]:
            raise Refuse(f"{st['fn'].name}: a return inside a step that is not the last (and the parent does not check for an early exit)")
        if st["early"] and any(r.value is None or (isinstance(r.value, ast.Constant) and r.value.value is None) for r in rets):
            raise Refuse(f"{st['fn'].name}: an early exit returning None would be read as 'go on'")
    for i, st in enumerate(steps):
        # a nested function that reads ctx.x sees the variable of its step: if a later step gives x a new value, the old code saw it, the new code would not
        inner = [n for n in ast.walk(st["fn"]) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)) and n is not st["fn"]]
        in_closure = {a for node, a, _m in st["uses"] if any(node in ast.walk(f) for f in inner)}
        later_writes = {w for s in steps[i + 1:] for w in s["writes"]}
        if in_closure & later_writes:
            raise Refuse(f"{st['fn'].name}: a nested function reads {sorted(in_closure & later_writes)}, which a later step sets again")
    return parent, head, init, steps, names, renamed


def transform(src: str, parent_name: str) -> str:
    nl = "\r\n" if "\r\n" in src else "\n"
    text = src.replace("\r\n", "\n")
    lines = text.split("\n")
    tree = ast.parse(text)
    parent, head, init, steps, names, renamed = _plan(tree, parent_name)

    def var(a: str) -> str:
        return a + "_" if a in renamed else a

    edits = []                                   # (line index, start, end, new text)
    inserts = []                                 # (after line index, [lines])
    for st in steps:
        fn = st["fn"]
        outs = [var(a) for a in st["outs"]]
        for node, attr, _m in st["uses"]:
            edits.append((node.lineno - 1, node.col_offset, node.end_col_offset, var(attr)))
        arg = fn.args.args[0]
        edits.append((arg.lineno - 1, arg.col_offset, arg.end_col_offset, ", ".join(var(p) for p in st["params"])))
        indent = " " * fn.body[0].col_offset
        if st["early"] and outs:
            # the step answers (early result or None, then the values to pass on): wrap each early result in parentheses and add placeholders
            for r in st["returns"]:
                edits.append((r.value.lineno - 1, r.value.col_offset, r.value.col_offset, "("))
                edits.append((r.value.end_lineno - 1, r.value.end_col_offset, r.value.end_col_offset, ")" + ", None" * len(outs)))
            inserts.append((fn.end_lineno, [f"{indent}return None, {', '.join(outs)}"]))
        elif outs:
            inserts.append((fn.end_lineno, [f"{indent}return {', '.join(outs)}"]))
        if st["maybe_unset"]:
            first = fn.body[0]
            doc = isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant)
            at = (first.end_lineno if doc else first.lineno - 1)
            inserts.append((at, [f"{indent}{var(n)} = None            # set below on some paths only" for n in st["maybe_unset"]]))
    for ln, a, b, new in sorted(edits, key=lambda e: (e[0], e[1], e[2]), reverse=True):      # right to left, bottom to top (a replacement before an insertion at its start)
        lines[ln] = lines[ln][:a] + new + lines[ln][b:]
    # the parent: initial values, then one call per step
    pbody = [s for s in parent.body if not (isinstance(s, ast.Expr) and isinstance(getattr(s, "value", None), ast.Constant))]
    indent = " " * pbody[0].col_offset
    new_body = [f"{indent}{var(k)} = {ast.unparse(v)}" for k, v in init if not (isinstance(v, ast.Name) and v.id == var(k))]
    for st in steps:
        call = f"{'await ' if st['awaited'] else ''}{st['fn'].name}({', '.join(var(p) for p in st['params'])})"
        outs = [var(a) for a in st["outs"]]
        if st is steps[-1]:
            new_body.append(f"{indent}{'return ' if st['returned'] else ''}{call}")
        elif st["early"]:
            new_body.append(f"{indent}{', '.join(['_result'] + outs)} = {call}")
            new_body += [f"{indent}if _result is not None:", f"{indent}    return _result"]
        else:
            new_body.append(f"{indent}{', '.join(outs)} = {call}" if outs else f"{indent}{call}")
    first, last = pbody[0].lineno - 1, parent.end_lineno
    for k in range(first, last):
        if "#" in lines[k]:
            raise Refuse(f"{parent_name}: a comment inside the function (line {k + 1}) would be lost")
    lines[first:last] = [None] * (last - first)
    lines[first] = "\n".join(new_body)
    for after, new in sorted(inserts, key=lambda i: -i[0]):          # insert from the bottom up so the indexes stay valid
        lines[after:after] = ["\n".join(new)]
    out = "\n".join(x for x in lines if x is not None)
    if "SimpleNamespace" not in out.replace("from types import SimpleNamespace\n", ""):
        out = out.replace("from types import SimpleNamespace\n", "", 1)
    ast.parse(out)
    return out.replace("\n", nl)


def flatten(src: str, outer_name: str, wrapper_names: list[str]) -> str:
    """Merge a two-level container into one. A wrapper is a step of OUTER that itself starts with `ctx = SimpleNamespace(ctx=ctx)` and calls steps that read the
    outer values as ctx.ctx.x and their own as ctx.y: the wrapper is removed, its steps are called straight from OUTER and read everything as ctx.x.
    Refused when an inner name is also an outer name (they would become one variable), or when a wrapper does more than call its steps."""
    nl = "\r\n" if "\r\n" in src else "\n"
    text = src.replace("\r\n", "\n")
    lines = text.split("\n")
    tree = ast.parse(text)
    funcs = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    outer = funcs[outer_name]
    obody = [s for s in outer.body if not (isinstance(s, ast.Expr) and isinstance(getattr(s, "value", None), ast.Constant))]
    seen_inner: dict[str, set] = {}
    all_steps = [c.func.id for s in obody[1:] for c in ast.walk(s) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.args and getattr(c.args[0], "id", "") == "ctx"]
    edits = []
    replace_call = {}                            # wrapper name -> list of step names
    for w in wrapper_names:
        fw = funcs[w]
        wb = [s for s in fw.body if not (isinstance(s, ast.Expr) and isinstance(getattr(s, "value", None), ast.Constant))]
        head = wb[0]
        if not (isinstance(head, ast.Assign) and getattr(head.targets[0], "id", "") == "ctx" and isinstance(head.value, ast.Call)
                and getattr(head.value.func, "id", "") == "SimpleNamespace" and [k.arg for k in head.value.keywords] == ["ctx"]):
            raise Refuse(f"{w}: does not start with ctx = SimpleNamespace(ctx=ctx)")
        steps = []
        for k, s in enumerate(wb[1:]):
            call = s.value if isinstance(s, (ast.Expr, ast.Return)) else None
            ok = isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and len(call.args) == 1 and getattr(call.args[0], "id", "") == "ctx"
            if not ok or (isinstance(s, ast.Return) and k != len(wb) - 2):
                raise Refuse(f"{w}: line {s.lineno} is not a plain step call")
            steps.append((call.func.id, isinstance(s, ast.Return)))
        inner_attrs = set()
        via_outer = set()                        # what the wrapper's steps reach in the outer container, as ctx.ctx.x
        for name, _r in steps:
            for node, attr, _m in _attrs(funcs[name]):
                inner_attrs.add(attr)
            for node in ast.walk(funcs[name]):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute) and node.value.attr == "ctx" \
                        and isinstance(node.value.value, ast.Name) and node.value.value.id == "ctx":
                    via_outer.add(node.attr)
        inner_attrs.discard("ctx")
        outer_all = {a for n in all_steps if n in funcs and n not in wrapper_names for _, a, _m in _attrs(funcs[n])} | via_outer
        clash = inner_attrs & outer_all
        if clash:
            raise Refuse(f"{w}: {sorted(clash)} are used both by the wrapper's own values and by the outer steps")
        for other, names_ in seen_inner.items():
            if inner_attrs & names_:
                raise Refuse(f"{w} and {other} use the same inner names {sorted(inner_attrs & names_)}")
        seen_inner[w] = inner_attrs
        # inside the wrapper's steps: ctx.ctx -> ctx
        for name, _r in steps:
            for node in ast.walk(funcs[name]):
                if isinstance(node, ast.Attribute) and node.attr == "ctx" and isinstance(node.value, ast.Name) and node.value.id == "ctx":
                    if node.lineno != node.end_lineno:
                        raise Refuse(f"{name}: ctx.ctx spans lines")
                    edits.append((node.lineno - 1, node.col_offset, node.end_col_offset, "ctx"))
        replace_call[w] = steps
    # OUTER: a call of a wrapper becomes the calls of its steps
    for s in obody[1:]:
        call = s.value if isinstance(s, (ast.Expr, ast.Return)) else None
        awaited = isinstance(call, ast.Await)
        call = call.value if awaited else call
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id in replace_call:
            ind = " " * s.col_offset
            new = []
            for name, was_return in replace_call[call.func.id]:
                new.append(f"{ind}{'return ' if was_return else ''}{'await ' if awaited else ''}{name}(ctx)")
            edits.append(("stmt", s.lineno - 1, s.end_lineno, "\n".join(new)))
    for e in sorted([e for e in edits if e[0] != "stmt"], key=lambda e: (e[0], e[1], e[2]), reverse=True):
        lines[e[0]] = lines[e[0]][:e[1]] + e[3] + lines[e[0]][e[2]:]
    for _tag, a, b, new in sorted([e for e in edits if e[0] == "stmt"], key=lambda e: -e[1]):
        lines[a:b] = [new]
    # the wrappers themselves go (from the bottom up)
    for w in sorted(wrapper_names, key=lambda n: -funcs[n].lineno):
        fw = funcs[w]
        start = fw.lineno - 1 - len(fw.decorator_list)
        end = fw.end_lineno
        while end < len(lines) and lines[end].strip() == "" and (end - fw.end_lineno) < 2:
            end += 1
        del lines[start:end]
    out = "\n".join(lines)
    ast.parse(out)
    return out.replace("\n", nl)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    path = Path(args[0])
    raw = path.read_bytes().decode("utf-8")
    try:
        flat = next((a.split("=", 1)[1].split(",") for a in sys.argv if a.startswith("--flatten=")), None)
        if flat:
            raw = flatten(raw, args[1], flat)
        new = transform(raw, args[1])
    except Refuse as exc:
        print("REFUSED:", exc)
        sys.exit(2)
    if "--write" in sys.argv:
        path.write_bytes(new.encode("utf-8"))
        print("written:", path)
    else:
        import difflib
        print("".join(list(difflib.unified_diff(raw.replace("\r\n", "\n").splitlines(True), new.replace("\r\n", "\n").splitlines(True), "before", "after"))[:200]))
