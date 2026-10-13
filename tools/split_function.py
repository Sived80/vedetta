"""Split one long function into steps, mechanically.
  python tools/split_function.py FILE FUNC START:name START:name ...  [--write]
Each START is the first line of a step (a top-level statement of FUNC); a step runs up to the next START (the last one to the end). The names
that cross from one step to another (or come from the parameters) become attributes of a small context object `ctx`; the names used inside one
step only stay local. Every step becomes a module-level function `_<FUNC>_<name>(ctx)` (async if it awaits) placed before FUNC, which is
rewritten as the list of calls. Comments are kept (the text is cut, not regenerated). Without --write it only reports what it would do.
Names bound by a late import and used in another step are reported: put the cut point somewhere else."""
import ast
import sys
from pathlib import Path

args = [a for a in sys.argv[1:] if not a.startswith("--")]
write = "--write" in sys.argv
auto = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--auto=")), 0)
path, fname = Path(args[0]), args[1]
cuts = [(int(a.split(":")[0]), a.split(":")[1]) for a in args[2:]]
raw = path.read_bytes().decode("utf-8")
nl = "\r\n" if "\r\n" in raw else "\n"
src = raw.replace("\r\n", "\n")
lines = src.split("\n")
tree = ast.parse(src)
fn = next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fname)
params = [a.arg for a in fn.args.args + fn.args.kwonlyargs]
body = fn.body
first = body[0].lineno if not (isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant)) else body[1].lineno
doc = body[0] if first != body[0].lineno else None
stmts = [s for s in body if s is not doc]
if auto:                      # cut at statement boundaries every ~auto lines (a statement is never cut), named part1, part2...
    cuts, acc, k = [], 0, 1
    for s in stmts:
        n = s.end_lineno - s.lineno + 1
        if not cuts or (acc >= auto and not isinstance(s, ast.Return)):
            cuts.append((s.lineno, f"part{k}"))
            k, acc = k + 1, 0
        acc += n
starts = [c[0] for c in cuts]
assert stmts[0].lineno == starts[0], f"first step must start at line {stmts[0].lineno}"
for s in starts:
    assert any(st.lineno == s for st in stmts), f"line {s} is not the start of a top-level statement"


def step_of(stmt):
    k = 0
    for i, s in enumerate(starts):
        if stmt.lineno >= s:
            k = i
    return k


class Scan(ast.NodeVisitor):
    """Names stored / loaded in one step, ignoring the variables bound by comprehensions and lambdas."""
    def __init__(self):
        self.stores, self.loads, self.imports, self.awaits, self.bound = set(), set(), set(), False, []

    def visit_Name(self, node):
        if node.id in self.bound[-1] if self.bound else False:
            return
        (self.stores if isinstance(node.ctx, (ast.Store, ast.Del)) else self.loads).add(node.id)

    def _scoped(self, node, targets):
        names = {n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)}
        self.bound.append((self.bound[-1] if self.bound else set()) | names)
        self.generic_visit(node)
        self.bound.pop()

    def visit_ListComp(self, n): self._scoped(n, [g.target for g in n.generators])
    visit_SetComp = visit_DictComp = visit_GeneratorExp = visit_ListComp

    def visit_Lambda(self, n): self._scoped(n, [ast.Name(id=a.arg) for a in n.args.args])

    def visit_FunctionDef(self, n):
        self.stores.add(n.name)                       # a nested function is a name defined in this step
        self._scoped(n, [ast.Name(id=a.arg) for a in n.args.args + n.args.kwonlyargs])
    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Await(self, n):
        self.awaits = True
        self.generic_visit(n)

    def visit_ImportFrom(self, n): self.imports.update((a.asname or a.name) for a in n.names)
    def visit_Import(self, n): self.imports.update((a.asname or a.name).split(".")[0] for a in n.names)


scans = []
for k in range(len(cuts)):
    sc = Scan()
    for s in stmts:
        if step_of(s) == k:
            sc.visit(s)
    scans.append(sc)
stores_in = [sc.stores | sc.imports for sc in scans]
shared = set(params)
for k, sc in enumerate(scans):
    for name in sc.loads:
        if any(name in stores_in[j] for j in range(len(cuts)) if j != k):
            shared.add(name)
# Late imports (anywhere in the function, also inside an `if`) used by a step that does not import them: the import is repeated at the top of
# that step (cheap, and the module stays imported late) instead of being handed over through ctx.
import_text = {}
for node in ast.walk(fn):
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        stmt = "\n".join(l.strip() for l in lines[node.lineno - 1:node.end_lineno])
        for al in node.names:
            import_text.setdefault((al.asname or al.name).split(".")[0], stmt)
late = sorted(n for n in import_text if n not in params and any(n in sc.loads and n not in sc.imports for sc in scans))
if late:
    print("late-import names repeated at the top of the steps that use them:", late)
shared -= set(import_text)        # an import never travels through ctx
shared = {n for n in shared if n in params or any(n in st for st in stores_in)}


def edits_for(stmt):
    """(lineno, col, end_col, replacement) for every Name of a shared variable in this statement, outside comprehension scopes that rebind it."""
    out = []

    def walk(node, bound):
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            bound = bound | {n.id for g in node.generators for n in ast.walk(g.target) if isinstance(n, ast.Name)}
        if isinstance(node, (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef)):
            bound = bound | {a.arg for a in node.args.args + node.args.kwonlyargs}
        if isinstance(node, ast.Name) and node.id in shared and node.id not in bound:
            out.append((node.lineno, node.col_offset, node.end_col_offset, "ctx." + node.id))
        for child in ast.iter_child_nodes(node):
            walk(child, bound)
    walk(stmt, set())
    return out


pieces, calls = [], []
for k, (start, name) in enumerate(cuts):
    members = [s for s in stmts if step_of(s) == k]
    a = members[0].lineno
    # keep the comment lines right above the first statement of the step
    while a - 2 >= 0 and lines[a - 2].strip().startswith("#") and not any(s.lineno <= a - 1 <= s.end_lineno for s in stmts if s not in members):
        a -= 1
    b = members[-1].end_lineno
    text = lines[a - 1:b]
    ed = sorted((e for s in members for e in edits_for(s)), reverse=True)
    for ln, c, ec, rep in ed:
        row = text[ln - a]
        b_row = row.encode("utf-8")
        text[ln - a] = (b_row[:c] + rep.encode("utf-8") + b_row[ec:]).decode("utf-8")
    hand = []                       # (statement end line, line) : names handed over to the other steps through ctx, placed right after their definition
    for s in members:
        if isinstance(s, (ast.Import, ast.ImportFrom)):
            hand += [(s.end_lineno, f"    ctx.{al} = {al}") for al in [(x.asname or x.name).split(".")[0] for x in s.names] if al in shared]
        elif isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)) and s.name in shared:
            hand.append((s.end_lineno, f"    ctx.{s.name} = {s.name}"))
    for end, line in sorted(hand, key=lambda h: -h[0]):
        text.insert(end - a + 1, line)
    for n in late:
        if n in scans[k].loads and n not in scans[k].imports:
            text.insert(0, "    " + import_text[n].replace("\n", "\n    "))
    # the body keeps its indentation (4 spaces: it was inside the function), which is what a function body needs
    asy = scans[k].awaits
    ret = isinstance(members[-1], ast.Return)
    pieces.append(f"{'async ' if asy else ''}def _{fname}_{name}(ctx){' -> dict' if ret else ''}:\n" + "\n".join(text) + "\n")
    last = k == len(cuts) - 1
    early = [n for m in members for n in ast.walk(m) if isinstance(n, ast.Return)]
    if not last and any(n.value is None or (isinstance(n.value, ast.Constant) and n.value.value is None) for n in early):
        sys.exit(f"step {name} has a bare `return`: cut elsewhere (a step ends the function only by returning a value)")
    call = f"{'await ' if asy else ''}_{fname}_{name}(ctx)"
    if ret and last:
        calls.append(f"    return {call}")
    elif early and not last:                  # the step may finish the whole function: it returns the result, else None
        calls.append(f"    _result = {call}")
        calls.append("    if _result is not None:")
        calls.append("        return _result")
    else:
        calls.append(f"    {call}")
header = lines[fn.lineno - 1:first - 1 if not doc else doc.end_lineno]
new_fn = "\n".join(header) + f"\n    ctx = SimpleNamespace({', '.join(f'{p}={p}' for p in params)})\n" + "\n".join(calls) + "\n"
print(f"{fname}: {len(cuts)} steps, shared across steps: {len(shared)} names -> {sorted(shared)}")
for (start, name), sc in zip(cuts, scans):
    print(f"  step {name}: line {start}{' (async)' if sc.awaits else ''}")
if write:
    fn_start = fn.lineno
    # decorators (none expected) stay above; the old function is replaced by the steps + the new function
    new_src = "\n".join(lines[:fn_start - 1]) + "\n" + "\n\n".join(pieces) + "\n\n" + new_fn + "\n".join(lines[fn.end_lineno:])
    if "from types import SimpleNamespace" not in new_src:
        new_src = "from types import SimpleNamespace\n" + new_src
    path.write_bytes(new_src.replace("\n", nl).encode("utf-8"))
    print("written", path)
