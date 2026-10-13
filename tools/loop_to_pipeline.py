"""Rewrites the loops that have an exact plainer form (Fowler, "Replace Loop with Pipeline"), and only those:
  find     for T in IT:  if C: return V      +  return D      ->  return next((V for T in IT if C), D)      (any(C for T in IT) when V is True and D is False)
  collect  out = []  +  for T in IT: [if C:] out.append(E)    ->  out = [E for T in IT [if C]]
  dict     d = {}  +  for T in IT: [if C:] d[K] = V           ->  d = {K: V for T in IT [if C]}
A loop is touched only if its whole text (the loop and the statement it is paired with) has no comment, no `else`, no `break`/`continue`, a single `if` at most, and the new line fits in 150 columns;
anything else is left as it is. The new text is written by ast.unparse for that statement only: the rest of the file is not reformatted.
    python tools/loop_to_pipeline.py FILE [FILE ...] [--write]     (without --write it only shows what it would do)"""
import ast
import sys
from pathlib import Path

WIDTH = 150


def target(node) -> str:
    """The loop target the way a person writes it in a comprehension: `a, b`, not `(a, b)`."""
    return ", ".join(ast.unparse(e) for e in node.elts) if isinstance(node, ast.Tuple) else ast.unparse(node)


def tidy(text: str) -> str:
    """ast.unparse wraps a generator argument in a second pair of parentheses: any((x for x in y)) -> any(x for x in y)."""
    for fn in ("any", "all", "sum", "min", "max", "sorted", "set", "list", "tuple"):
        key = fn + "(("
        i = text.find(key)
        while i != -1:
            start = i + len(fn) + 1                      # the inner "("
            depth, j = 0, start
            while j < len(text):
                depth += text[j] == "("
                depth -= text[j] == ")"
                if depth == 0:
                    break
                j += 1
            if j + 1 < len(text) and text[j + 1] == ")" and " for " in text[start:j]:
                text = text[:start] + text[start + 1:j] + text[j + 1:]
            i = text.find(key, i + 1)
    return double_quotes(text)


def double_quotes(text: str) -> str:
    """ast.unparse writes 'single' quotes; the code of the project uses "double" ones (kept when the text has a double quote or a backslash)."""
    import io
    import tokenize
    out, last = [], 0
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.STRING and tok.start[0] == tok.end[0]:
                s = tok.string
                prefix = s[:len(s) - len(s.lstrip("rbfuRBFU"))]
                body = s[len(prefix):]
                if body.startswith("'") and body.endswith("'") and not body.startswith("'''") and '"' not in body and "\\" not in body:
                    out.append(text[last:tok.start[1]] + prefix + '"' + body[1:-1] + '"')
                    last = tok.end[1]
        out.append(text[last:])
    except tokenize.TokenError:
        return text
    return "".join(out)


def simple_body(body):
    """([condition or None], inner statement) of a body that is one statement, possibly under one `if` without else."""
    if len(body) == 1 and isinstance(body[0], ast.If) and not body[0].orelse and len(body[0].body) == 1:
        return body[0].test, body[0].body[0]
    if len(body) == 1:
        return None, body[0]
    return "NO", None


def clean(loop) -> bool:
    return not loop.orelse and not any(isinstance(n, (ast.Break, ast.Continue)) for n in ast.walk(loop))


def rewrite_block(stmts, lines):
    """[(first_line, last_line, new_text)] for the statements of one block."""
    out = []
    for i, st in enumerate(stmts):
        if not isinstance(st, ast.For) or not clean(st) or i + 0 >= len(stmts):
            continue
        cond, inner = simple_body(st.body)
        if cond == "NO":
            continue
        indent = " " * st.col_offset
        # find: for ...: if C: return V  followed by  return D
        if cond is not None and isinstance(inner, ast.Return) and inner.value is not None and i + 1 < len(stmts) and isinstance(stmts[i + 1], ast.Return) and stmts[i + 1].value is not None:
            default = stmts[i + 1].value
            if any(isinstance(n, ast.Call) for n in ast.walk(stmts[i + 1].value)):      # next() evaluates its default BEFORE the search: only a plain value keeps the order of the original
                continue
            val = inner.value
            if isinstance(val, ast.Constant) and val.value is True and isinstance(default, ast.Constant) and default.value is False:
                text = "return any(%s for %s in %s)" % (ast.unparse(cond), target(st.target), ast.unparse(st.iter))
            else:
                text = "return next((%s for %s in %s if %s), %s)" % (ast.unparse(val), target(st.target), ast.unparse(st.iter), ast.unparse(cond), ast.unparse(default))
            out.append((st.lineno, stmts[i + 1].end_lineno, indent + text))
        # collect / dict: the statement before is the empty container, the loop only fills it
        if i > 0 and isinstance(stmts[i - 1], ast.Assign) and len(stmts[i - 1].targets) == 1 and isinstance(stmts[i - 1].targets[0], ast.Name):
            name = stmts[i - 1].targets[0].id
            init = stmts[i - 1].value
            tail = " if %s" % ast.unparse(cond) if cond is not None else ""
            if isinstance(init, ast.List) and not init.elts and isinstance(inner, ast.Expr) and isinstance(inner.value, ast.Call) and isinstance(inner.value.func, ast.Attribute) \
                    and inner.value.func.attr == "append" and isinstance(inner.value.func.value, ast.Name) and inner.value.func.value.id == name and len(inner.value.args) == 1:
                text = "%s = [%s for %s in %s%s]" % (name, ast.unparse(inner.value.args[0]), target(st.target), ast.unparse(st.iter), tail)
                out.append((stmts[i - 1].lineno, st.end_lineno, indent + text))
            elif isinstance(init, ast.Dict) and not init.keys and isinstance(inner, ast.Assign) and len(inner.targets) == 1 and isinstance(inner.targets[0], ast.Subscript) \
                    and isinstance(inner.targets[0].value, ast.Name) and inner.targets[0].value.id == name:
                text = "%s = {%s: %s for %s in %s%s}" % (name, ast.unparse(inner.targets[0].slice), ast.unparse(inner.value), target(st.target), ast.unparse(st.iter), tail)
                out.append((stmts[i - 1].lineno, st.end_lineno, indent + text))
    kept = []
    for first, last, text in out:
        text = tidy(text)
        span = lines[first - 1:last]
        if any("#" in l for l in span) or len(text) > WIDTH or "\n" in text:
            continue
        kept.append((first, last, text))
    return kept


def blocks_of(tree):
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            stmts = getattr(node, field, None)
            if isinstance(stmts, list) and stmts and isinstance(stmts[0], ast.stmt):
                yield stmts
        for h in getattr(node, "handlers", []) or []:
            yield h.body


def main() -> int:
    paths = [Path(a) for a in sys.argv[1:] if not a.startswith("--")]
    write = "--write" in sys.argv
    total = 0
    for p in paths:
        raw = p.read_bytes().decode("utf-8")
        crlf = "\r\n" in raw
        text = raw.replace("\r\n", "\n")
        lines = text.split("\n")
        tree = ast.parse(text)
        edits = {}
        for stmts in blocks_of(tree):
            for first, last, new in rewrite_block(stmts, lines):
                edits[(first, last)] = new
        # nested edits: keep the outermost only
        ordered = sorted(edits.items())
        final, last_end = [], 0
        for (first, last), new in ordered:
            if first > last_end:
                final.append((first, last, new))
                last_end = last
        for first, last, new in final:
            print("%s:%d-%d  ->  %s" % (p.name, first, last, new.strip()[:140]))
        total += len(final)
        if write and final:
            for first, last, new in reversed(final):
                lines[first - 1:last] = [new]
            out = "\n".join(lines)
            ast.parse(out)
            p.write_bytes((out.replace("\n", "\r\n") if crlf else out).encode("utf-8"))
    print("rewrites %s: %d" % ("written" if write else "proposed", total))
    print("DONE_PIPELINE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
