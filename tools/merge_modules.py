"""Put several small modules of the same package into one coherent module (the opposite of split_module.py), keeping everything working.
  python tools/merge_modules.py TARGET SOURCE [SOURCE ...] [--write]        (module names without .py, all in vedetta/app)
What it does: the top-level items of every SOURCE are appended to TARGET (each after a one-line section comment taken from the source's docstring), the imports they need are added to
TARGET's import block, references between the merged modules become plain names, the SOURCE files are removed (git rm), and everywhere else (application, tests, tools) the name of a
merged module is replaced by TARGET - in `from . import a, b` lists (without duplicates), in `module.name` accesses and in comments. It stops, touching nothing, if two modules define
the same name. If TARGET does not exist yet, the first SOURCE is renamed to it (git mv). Golden files (tests/golden) are never edited."""
import ast
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
APP = REPO / "vedetta" / "app"
FUNC = (ast.FunctionDef, ast.AsyncFunctionDef)


def top_names(tree) -> set:
    out = set()
    for n in tree.body:
        if isinstance(n, FUNC + (ast.ClassDef,)):
            out.add(n.name)
        elif isinstance(n, ast.Assign):
            out |= {t.id for t in n.targets if isinstance(t, ast.Name)}
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            out.add(n.target.id)
    return out


def read(p: Path) -> str:
    return p.read_bytes().decode("utf-8").replace("\r\n", "\n")


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    write = "--write" in sys.argv
    target, sources = args[0], args[1:]
    merged = set(sources) | {target}
    tpath = APP / (target + ".py")
    created = False
    if not tpath.exists():
        first = sources.pop(0)
        if write:
            subprocess.run(["git", "mv", str(APP / (first + ".py")), str(tpath)], cwd=REPO, check=True)
        else:
            tpath = APP / (first + ".py")
        created = True
        merged_rename = {first: target}
    else:
        merged_rename = {}
    ttext = read(tpath)
    ttree = ast.parse(ttext)
    defined = top_names(ttree)
    plan = []
    for s in sources:
        stext = read(APP / (s + ".py"))
        stree = ast.parse(stext)
        clash = defined & top_names(stree)
        if clash:
            print("STOP: %s and the target both define %s" % (s, sorted(clash)))
            return 1
        defined |= top_names(stree)
        plan.append((s, stext, stree))
    # imports already in the target
    have = set()
    for n in ttree.body:
        if isinstance(n, ast.ImportFrom):
            have |= {(n.level, n.module, a.name, a.asname) for a in n.names}
        elif isinstance(n, ast.Import):
            have |= {(0, None, a.name, a.asname) for a in n.names}
    new_imports, bodies = [], []
    for s, stext, stree in plan:
        lines = stext.split("\n")
        doc = ast.get_docstring(stree) or s
        header = "# --- " + doc.split("\n")[0].split(". ")[0].rstrip(".") + " (was %s.py)" % s
        segs = []
        prev_end = 0
        for n in stree.body:
            start = min([n.lineno] + [d.lineno for d in getattr(n, "decorator_list", [])])
            first = prev_end + 1
            while first < start and lines[first - 1].strip() == "":
                first += 1
            prev_end = n.end_lineno
            if isinstance(n, ast.Expr) and isinstance(getattr(n, "value", None), ast.Constant) and isinstance(n.value.value, str) and n is stree.body[0]:
                continue                                              # the module docstring
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                if isinstance(n, ast.ImportFrom) and n.level and not n.module and any(a.name in merged for a in n.names):
                    keep = [a for a in n.names if a.name not in merged]
                    if not keep:
                        continue
                    n.names = keep
                keys = {(getattr(n, "level", 0), getattr(n, "module", None), a.name, a.asname) for a in n.names} if isinstance(n, ast.ImportFrom) else {(0, None, a.name, a.asname) for a in n.names}
                if keys <= have:
                    continue
                have |= keys
                new_imports.append(ast.unparse(n) if isinstance(n, ast.ImportFrom) and n.level and not n.module else "\n".join(lines[first - 1:n.end_lineno]))
                continue
            segs.append("\n".join(lines[first - 1:n.end_lineno]))
        bodies.append((header, segs))
    last_import = max((n.end_lineno for n in ttree.body if isinstance(n, (ast.Import, ast.ImportFrom))), default=0)
    tl = ttext.split("\n")
    out = tl[:last_import] + new_imports + tl[last_import:]
    while out and out[-1] == "":
        out.pop()
    for header, segs in bodies:
        out += ["", "", header, ""] + ["\n\n".join(segs)]
    new = "\n".join(out) + "\n"
    # references between the merged modules become plain names
    for m in merged | set(merged_rename):
        new = re.sub(r"\b%s\.(?=[A-Za-z_])" % m, "", new)
    ast.parse(new)
    print("target %s: %d lines after the merge (sources: %s)" % (target, new.count("\n"), ", ".join(sources + list(merged_rename))))
    if not write:
        print("DONE_MERGE (dry run)")
        return 0
    tpath.write_bytes(new.replace("\n", "\r\n").encode("utf-8") if "\r\n" in tpath.read_bytes().decode("utf-8") else new.encode("utf-8"))
    removed = [s for s, _, _ in plan]
    for s in removed:
        subprocess.run(["git", "rm", "-q", "-f", str(APP / (s + ".py"))], cwd=REPO, check=True)
    gone = set(removed) | set(merged_rename)
    gone.discard(target)
    for base in (REPO / "vedetta", REPO / "tests", REPO / "tools"):
        for f in base.rglob("*.py"):
            if "golden" in f.parts or f == Path(__file__).resolve() or f.resolve() == tpath.resolve():
                continue
            raw = f.read_bytes().decode("utf-8")
            text = raw.replace("\r\n", "\n")
            orig = text

            def fix_import(m):
                names = [x.strip() for x in m.group(2).split(",")]
                seen, res = set(), []
                for x in names:
                    x = target if x in gone else x
                    if x not in seen:
                        seen.add(x)
                        res.append(x)
                return m.group(1) + ", ".join(res)
            text = re.sub(r"^(\s*(?:from \.+ import |from app import ))([^\n(]+)$", fix_import, text, flags=re.M)
            for g in gone:
                text = re.sub(r"\b%s\b(?!\.json)" % g, target, text)
            if text != orig:
                f.write_bytes((text.replace("\n", "\r\n") if "\r\n" in raw else text).encode("utf-8"))
                print("references updated in", f.relative_to(REPO))
    print("DONE_MERGE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
