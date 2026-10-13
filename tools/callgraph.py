"""How tangled is the chain of calls? A static map of who calls whom inside the app (names resolved through the imports; calls on objects whose class is unknown are not followed, so the numbers are a
lower bound). It reports: functions that only pass the call on (middle men), the longest chains of calls, the functions that call many others, and the coupling between modules.
    python tools/callgraph.py [APP_DIR] [--list]"""
import ast
import sys
from collections import Counter, defaultdict
from pathlib import Path

FUNC = (ast.FunctionDef, ast.AsyncFunctionDef)


def module_name(root: Path, f: Path) -> str:
    return ".".join(f.relative_to(root).with_suffix("").parts)


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    root = Path(args[0]) if args else Path(__file__).resolve().parent.parent / "vedetta" / "app"
    files = [f for f in sorted(root.rglob("*.py")) if "__pycache__" not in f.parts and f.name != "__init__.py"]
    mods = {module_name(root, f): f for f in files}
    short = defaultdict(list)
    for m in mods:
        short[m.split(".")[-1]].append(m)
    trees = {m: ast.parse(f.read_text(encoding="utf-8")) for m, f in mods.items()}
    funcs = {}          # (module, qualname) -> node
    for m, t in trees.items():
        for n in t.body:
            if isinstance(n, FUNC):
                funcs[(m, n.name)] = n
            elif isinstance(n, ast.ClassDef):
                for b in n.body:
                    if isinstance(b, FUNC):
                        funcs[(m, n.name + "." + b.name)] = b

    def resolve_mod(cur: str, level: int, module: str | None):
        parts = cur.split(".")[:-1]
        base = parts[:len(parts) - (level - 1)] if level else []
        cand = ".".join(base + (module.split(".") if module else []))
        return cand if cand in mods else None

    aliases = {}        # module -> {local name: ("mod", module) | ("func", module, name)}
    imports_of = defaultdict(set)
    for m, t in trees.items():
        al = {}
        for n in ast.walk(t):
            if isinstance(n, ast.ImportFrom) and n.level:
                base = resolve_mod(m, n.level, n.module)
                for a in n.names:
                    sub = resolve_mod(m, n.level, ((n.module + ".") if n.module else "") + a.name)
                    if sub:
                        al[a.asname or a.name] = ("mod", sub)
                        imports_of[m].add(sub)
                    elif base:
                        al[a.asname or a.name] = ("func", base, a.name)
                        imports_of[m].add(base)
        aliases[m] = al
    edges = defaultdict(set)
    for (m, q), fn in funcs.items():
        cls = q.split(".")[0] if "." in q else None
        for c in ast.walk(fn):
            if not isinstance(c, ast.Call):
                continue
            f = c.func
            tgt = None
            if isinstance(f, ast.Name):
                if (m, f.id) in funcs:
                    tgt = (m, f.id)
                elif aliases[m].get(f.id, ("",))[0] == "func" and (aliases[m][f.id][1], aliases[m][f.id][2]) in funcs:
                    tgt = (aliases[m][f.id][1], aliases[m][f.id][2])
            elif isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
                if f.value.id == "self" and cls and (m, cls + "." + f.attr) in funcs:
                    tgt = (m, cls + "." + f.attr)
                elif aliases[m].get(f.value.id, ("",))[0] == "mod" and (aliases[m][f.value.id][1], f.attr) in funcs:
                    tgt = (aliases[m][f.value.id][1], f.attr)
            if tgt and tgt != (m, q):
                edges[(m, q)].add(tgt)

    def body_of(fn):
        return [b for b in fn.body if not (isinstance(b, ast.Expr) and isinstance(getattr(b, "value", None), ast.Constant) and isinstance(b.value.value, str))]

    middle = []
    for key, fn in funcs.items():
        body = body_of(fn)
        if len(body) == 1:
            s = body[0]
            v = s.value if isinstance(s, (ast.Return, ast.Expr)) else None
            if isinstance(v, ast.Await):
                v = v.value
            if isinstance(v, ast.Call) and key in edges and len(edges[key]) == 1:
                params = {a.arg for a in fn.args.args + fn.args.kwonlyargs} | {"self"}
                names = {x.id for x in ast.walk(v) if isinstance(x, ast.Name)}
                if names <= params | {"state", "history"} or True:
                    middle.append((key, next(iter(edges[key]))))
    # longest chains (depth-first, cycles cut)
    memo, onstack = {}, set()

    def depth(k):
        if k in memo:
            return memo[k]
        if k in onstack:
            return (0, [k])
        onstack.add(k)
        best = (0, [k])
        for t in edges.get(k, ()):
            d, p = depth(t)
            if d + 1 > best[0]:
                best = (d + 1, [k] + p)
        onstack.discard(k)
        memo[k] = best
        return best

    called = {t for ts in edges.values() for t in ts}
    chains = sorted((depth(k) for k in funcs if k not in called), key=lambda x: -x[0])
    fan = Counter({k: len(v) for k, v in edges.items()})
    fan_in = Counter(m for ms in imports_of.values() for m in ms)
    print("functions %d | calls between them %d | functions that only pass the call on: %d (%.1f%%)" % (len(funcs), sum(len(v) for v in edges.values()), len(middle), 100 * len(middle) / len(funcs)))
    print("longest chains of calls (functions deep): %s" % [c[0] for c in chains[:5]])
    for d, p in chains[:3]:
        print("  %d: %s" % (d, " > ".join("%s.%s" % (m.split(".")[-1], q) for m, q in p)))
    print("functions that call more than 8 other app functions: %d  most: %s" % (sum(1 for v in fan.values() if v > 8), [("%s.%s" % (k[0].split(".")[-1], k[1]), v) for k, v in fan.most_common(4)]))
    out_deg = {m: len(v) for m, v in imports_of.items()}
    print("modules: %d | imports of another app module per module: mean %.1f, most %s" % (len(mods), sum(out_deg.values()) / max(len(mods), 1), sorted(out_deg.items(), key=lambda kv: -kv[1])[:4]))
    print("most imported modules: %s" % fan_in.most_common(5))
    if "--list" in sys.argv:
        for (m, q), t in middle:
            print("  middle man: %s.%s -> %s.%s" % (m, q, t[0], t[1]))
    print("DONE_CALLS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
