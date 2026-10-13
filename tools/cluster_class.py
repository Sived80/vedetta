"""Static map of a class: which self.<attr> each method reads or writes, and which methods it calls.
Groups the methods that share state, to decide where a class can be cut. Usage: python tools/cluster_class.py app/state.py DeviceState"""
import ast
import sys
from collections import defaultdict

path, cls = sys.argv[1], sys.argv[2]
tree = ast.parse(open(path, encoding="utf-8").read())
klass = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
methods = {n.name: n for n in klass.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
uses, calls = {}, {}
for name, fn in methods.items():
    a, c = set(), set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "self":
            (c if n.attr in methods else a).add(n.attr)
    uses[name], calls[name] = a, c
# union-find on shared attributes (ignoring attributes used by more than 6 methods: they glue everything)
users = defaultdict(set)
for m, a in uses.items():
    for x in a:
        users[x].add(m)
hub = {x for x, ms in users.items() if len(ms) > int(sys.argv[3] if len(sys.argv) > 3 else 6)}
parent = {m: m for m in methods}
def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x
for x, ms in users.items():
    if x in hub:
        continue
    ms = list(ms)
    for m in ms[1:]:
        parent[find(m)] = find(ms[0])
groups = defaultdict(list)
for m in methods:
    groups[find(m)].append(m)
print(f"{cls}: {len(methods)} methods, {sum(f.end_lineno - f.lineno + 1 for f in methods.values())} lines")
print("hub attributes (used by many methods, shared by everything):", ", ".join(sorted(hub)))
for g in sorted(groups.values(), key=lambda g: -sum(methods[m].end_lineno - methods[m].lineno + 1 for m in g)):
    lines = sum(methods[m].end_lineno - methods[m].lineno + 1 for m in g)
    attrs = sorted({x for m in g for x in uses[m] if x not in hub})
    print(f"\n[{lines} lines] {', '.join(sorted(g))}\n   own state: {', '.join(attrs) or '-'}")
