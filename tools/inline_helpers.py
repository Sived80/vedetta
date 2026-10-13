"""Puts back into its caller a private helper that has no life of its own: a module-level function with a leading underscore, no docstring (a docstring means the name carries an idea), no decorator,
only positional parameters and a body of one `return <expression>`, used exactly once, in the same file, and named by no test and no other module. The call is replaced by the expression with the
arguments in place of the parameters; only plain arguments (names, constants, attribute chains) are accepted, so nothing is evaluated twice or skipped; a name that the expression takes from the module
must not be shadowed by a local name at the call site. Anything else is left alone.
    python tools/inline_helpers.py FILE [FILE ...] [--write]"""
import ast
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from loop_to_pipeline import tidy  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
FUNC = (ast.FunctionDef, ast.AsyncFunctionDef)
PLAIN = (ast.Name, ast.Constant)


def plain(node) -> bool:
    if isinstance(node, PLAIN):
        return True
    return isinstance(node, ast.Attribute) and plain(node.value)


def local_names(fn) -> set:
    out = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
    for n in ast.walk(fn):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            out.add(n.id)
    return out


class Substitute(ast.NodeTransformer):
    def __init__(self, mapping):
        self.mapping = mapping

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load) and node.id in self.mapping:
            return ast.copy_location(self.mapping[node.id], node)
        return node


def repo_text() -> str:
    return "\n".join(p.read_text(encoding="utf-8", errors="ignore") for base in ("vedetta", "tests", "tools") for p in (REPO / base).rglob("*.py") if "__pycache__" not in p.parts)


def main() -> int:
    paths = [Path(a) for a in sys.argv[1:] if not a.startswith("--")]
    write = "--write" in sys.argv
    everything = repo_text() + chr(10) + chr(10).join(p.read_text(encoding=chr(117)+chr(116)+chr(102)+chr(45)+chr(56)) for p in paths if REPO not in p.resolve().parents)      # files outside the repository (the tests of this tool) count too
    total = 0
    for p in paths:
        raw = p.read_bytes().decode("utf-8")
        crlf = "\r\n" in raw
        text = raw.replace("\r\n", "\n")
        tree = ast.parse(text)
        lines = text.split("\n")
        edits = []                                   # (first line, last line, new lines) in 1-based inclusive form, applied from the bottom
        used_callers = set()
        for fn in [n for n in tree.body if isinstance(n, ast.FunctionDef)]:
            if not fn.name.startswith("_") or fn.name.startswith("__") or fn.decorator_list or ast.get_docstring(fn):
                continue
            a = fn.args
            if a.defaults or a.kwonlyargs or a.vararg or a.kwarg or a.posonlyargs or len(fn.body) != 1 or not isinstance(fn.body[0], ast.Return) or fn.body[0].value is None:
                continue
            if len(re.findall(r"\b%s\b" % re.escape(fn.name), everything)) != 2:
                continue
            calls = [(c, outer) for outer in tree.body for c in ast.walk(outer) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == fn.name and outer is not fn]
            if len(calls) != 1:
                continue
            call, outer = calls[0]
            params = [x.arg for x in a.args]
            if call.keywords or len(call.args) != len(params) or not all(plain(x) for x in call.args) or id(outer) in used_callers:
                continue
            expr = fn.body[0].value
            free = {n.id for n in ast.walk(expr) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)} - set(params)
            if isinstance(outer, FUNC) and free & local_names(outer):
                continue
            if any(isinstance(n, (ast.Lambda, ast.NamedExpr, ast.Await, ast.Yield)) for n in ast.walk(expr)):
                continue
            new = ast.fix_missing_locations(Substitute(dict(zip(params, call.args))).visit(ast.parse(ast.unparse(expr), mode="eval").body))
            new_text = tidy(ast.unparse(new))
            # where the call sits: alone after `return`, or inside a bigger expression (then it is wrapped unless it is a plain atom)
            seg = ast.get_source_segment(text, call)
            if seg is None or call.lineno != call.end_lineno:
                continue
            atom = isinstance(new, (ast.Name, ast.Attribute, ast.Call, ast.Subscript, ast.Constant, ast.List, ast.Tuple, ast.Dict, ast.Set, ast.ListComp, ast.GeneratorExp))
            if not atom:
                line = lines[call.lineno - 1]
                stripped = line.strip()
                alone = stripped == seg or stripped == "return " + seg or (stripped.startswith(("x = ", "return ")) and stripped.endswith(seg) and stripped.count(seg) == 1 and stripped.split(seg)[0].strip() in ("return", ""))
                if not alone:
                    new_text = "(" + new_text + ")"
            line_no = call.lineno
            line = lines[line_no - 1]
            col0, col1 = call.col_offset, call.end_col_offset
            enc = line.encode("utf-8")
            replaced = (enc[:col0] + new_text.encode("utf-8") + enc[col1:]).decode("utf-8")
            if len(replaced) > 160 or "#" in lines[fn.lineno - 1:fn.end_lineno][0] and False:
                continue
            first = fn.lineno
            last = fn.end_lineno
            while last < len(lines) and lines[last].strip() == "":
                last += 1
            while first > 1 and lines[first - 2].strip().startswith("#"):
                first -= 1
            edits.append((line_no, line_no, [replaced]))
            edits.append((first, last, []))
            used_callers.add(id(outer))
            print("%s: %s inlined into %s:%d  ->  %s" % (p.name, fn.name, p.name, line_no, replaced.strip()[:110]))
            total += 1
        if write and edits:
            for first, last, new_lines in sorted(edits, reverse=True):
                lines[first - 1:last] = new_lines
            out = "\n".join(lines)
            ast.parse(out)
            p.write_bytes((out.replace("\n", "\r\n") if crlf else out).encode("utf-8"))
    print("helpers %s: %d" % ("inlined" if write else "that could be inlined", total))
    print("DONE_INLINE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
