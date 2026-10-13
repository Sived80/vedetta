"""How easy is the code to read for a person? Measures, on the Python code of the application:
  - cognitive complexity per function (our implementation of the published SonarSource rules: +1 for each break in the linear flow - if/elif/else, loops, except, conditional
    expression, a sequence of `and`/`or` - and one more for every level of nesting; not the official tool, so the numbers are indicative, the ranking is what counts);
  - functions above the reading threshold (15, the usual default);
  - private helpers written ABOVE their only caller (a reader meets the detail before the story: the stepdown rule wants the caller first);
  - modules without a docstring that says what they are for;
  - helpers of at most 10 lines used in exactly one place (candidates to be folded back into their caller).
    python tools/readability.py [APP_DIR] [--list]"""
import ast
import re
import sys
from collections import Counter
from pathlib import Path

THRESHOLD = 15


class Cognitive(ast.NodeVisitor):
    """Cognitive complexity of ONE function body (nested functions count with extra nesting)."""

    def __init__(self):
        self.score = 0
        self.depth = 0

    def _flow(self, node, body_fields=("body", "orelse")):
        self.score += 1 + self.depth
        self.depth += 1
        for field in body_fields:
            for child in getattr(node, field, []) or []:
                self.visit(child)
        self.depth -= 1

    def visit_If(self, node):
        self.score += 1 + self.depth
        self.visit(node.test)
        self.depth += 1
        for child in node.body:
            self.visit(child)
        self.depth -= 1
        orelse = node.orelse
        while orelse:
            if len(orelse) == 1 and isinstance(orelse[0], ast.If):     # elif: +1, no nesting penalty
                node = orelse[0]
                self.score += 1
                self.visit(node.test)
                self.depth += 1
                for child in node.body:
                    self.visit(child)
                self.depth -= 1
                orelse = node.orelse
            else:                                                       # else: +1
                self.score += 1
                self.depth += 1
                for child in orelse:
                    self.visit(child)
                self.depth -= 1
                break

    def visit_For(self, node):
        self.visit(node.iter)
        self._flow(node)
    visit_AsyncFor = visit_For

    def visit_While(self, node):
        self.visit(node.test)
        self._flow(node)

    def visit_Try(self, node):
        for child in node.body:
            self.visit(child)
        for handler in node.handlers:
            self.score += 1 + self.depth
            self.depth += 1
            for child in handler.body:
                self.visit(child)
            self.depth -= 1
        for child in node.orelse + node.finalbody:
            self.visit(child)

    def visit_IfExp(self, node):
        self.score += 1 + self.depth
        self.generic_visit(node)

    def visit_BoolOp(self, node):
        self.score += 1                                                 # one per sequence of the same operator
        for value in node.values:
            if not isinstance(value, ast.BoolOp):
                self.visit(value)
            else:
                self.visit_BoolOp_nested(value, type(node.op))

    def visit_BoolOp_nested(self, node, parent_op):
        if type(node.op) is not parent_op:
            self.score += 1
        for value in node.values:
            if isinstance(value, ast.BoolOp):
                self.visit_BoolOp_nested(value, type(node.op))
            else:
                self.visit(value)

    def visit_FunctionDef(self, node):                                  # a nested function: its body is read one level deeper
        self.depth += 1
        for child in node.body:
            self.visit(child)
        self.depth -= 1
    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node):
        self.depth += 1
        self.visit(node.body)
        self.depth -= 1

    def visit_comprehension_like(self, node):
        self.generic_visit(node)
    visit_ListComp = visit_SetComp = visit_DictComp = visit_GeneratorExp = visit_comprehension_like


def cognitive(fn) -> int:
    c = Cognitive()
    for child in fn.body:
        c.visit(child)
    return c.score


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    root = Path(args[0]) if args else Path(__file__).resolve().parent.parent / "vedetta" / "app"
    files = [f for f in sorted(root.rglob("*.py")) if "__pycache__" not in f.parts and f.name != "__init__.py"]
    texts = {f: f.read_text(encoding="utf-8") for f in files}
    code = "\n".join(texts.values())
    scores, upside, no_doc, fold = [], [], [], []
    for f, text in texts.items():
        tree = ast.parse(text)
        rel = str(f.relative_to(root))
        doc = ast.get_docstring(tree)
        if not doc or len(doc) < 25:
            no_doc.append(rel)
        top = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        pos = {n.name: n.lineno for n in top}
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                scores.append((cognitive(n), rel, n.name))
        callers = {}
        for fn in top:
            body = ast.dump(fn)
            for other in top:
                if other is not fn and other.name.startswith("_") and re.search(r"Name\(id='%s'" % re.escape(other.name), body):
                    callers.setdefault(other.name, []).append(fn.name)
        for name, who in callers.items():
            if len(who) == 1 and pos[name] < pos[who[0]]:
                upside.append((rel, name, who[0]))
        for fn in top:
            ln = fn.end_lineno - fn.lineno + 1
            if fn.name.startswith("_") and not fn.name.startswith("__") and ln <= 10 and len(re.findall(r"\b%s\b" % re.escape(fn.name), code)) - 1 == 1:
                fold.append((rel, fn.name, ln))
    n = len(scores)
    over = sorted((s for s in scores if s[0] > THRESHOLD), reverse=True)
    dist = Counter("0-5" if s[0] <= 5 else "6-10" if s[0] <= 10 else "11-15" if s[0] <= 15 else "16-25" if s[0] <= 25 else ">25" for s in scores)
    print("functions %d | cognitive complexity: %s | mean %.2f | above %d: %d" % (n, dict(dist), sum(s[0] for s in scores) / max(n, 1), THRESHOLD, len(over)))
    print("modules without a real docstring: %d of %d" % (len(no_doc), len(files)))
    print("private helpers above their only caller (reader meets the detail first): %d" % len(upside))
    print("short single-use helpers (<=10 lines, used once): %d" % len(fold))
    if "--list" in sys.argv:
        for s in over[:25]:
            print("  hard: %3d %s %s" % s)
        for rel in no_doc:
            print("  no docstring:", rel)
    else:
        print("hardest:", [(s[0], s[2]) for s in over[:6]])
    print("DONE_READ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
