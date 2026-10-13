"""Map of a module for splitting it by topic: every top-level function/constant, who calls it, and the groups that call each other.
  python tools/module_map.py FILE            groups (connected through calls between functions, module constants count as links only if used by 2+ groups)
Prints the group sizes and, for each group, its functions, the external names it needs from the other groups, and who outside calls it."""
import ast
import sys
from collections import defaultdict

path = sys.argv[1]
src = open(path, encoding="utf-8").read()
tree = ast.parse(src)
items = {}
for n in tree.body:
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        items[n.name] = n
    elif isinstance(n, (ast.Assign, ast.AnnAssign)):
        for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
            if isinstance(t, ast.Name):
                items[t.id] = n
uses = {k: {x.id for x in ast.walk(v) if isinstance(x, ast.Name)} & (set(items) - {k}) for k, v in items.items()}
funcs = [k for k, v in items.items() if isinstance(v, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
parent = {k: k for k in funcs}
def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x
for f in funcs:
    for u in uses[f]:
        if u in parent:
            parent[find(f)] = find(u)
groups = defaultdict(list)
for f in funcs:
    groups[find(f)].append(f)
consts = {k for k in items if k not in funcs}
for g in sorted(groups.values(), key=lambda g: -sum(items[m].end_lineno - items[m].lineno + 1 for m in g)):
    lines = sum(items[m].end_lineno - items[m].lineno + 1 for m in g)
    need = sorted({u for m in g for u in uses[m] if u in consts})
    print(f"[{lines:4d} lines, {len(g)} fn] {', '.join(sorted(g, key=lambda m: items[m].lineno))}")
    print(f"       module constants used: {', '.join(need) or '-'}")
