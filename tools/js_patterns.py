"""The forms of JavaScript that have a plainer or safer way (text only, comments and strings removed): `var` (let/const have block scope), `==` and `!=` (strict comparison), `else` right after a `return`
(a guard clause removes a level), index loops over an array that only read it (for...of), loops that only push into a list (map/filter), long functions, functions with many parameters and the deepest block
nesting of each function. Points at places to look at; the decision is made function by function.
    python tools/js_patterns.py [JS_DIR]"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from loops_js import match, strip  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent / "vedetta" / "app" / "frontend" / "ha" / "js"


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else ROOT
    totals = {"var": 0, "== / !=": 0, "else after return": 0, "index loop": 0, "loop that only pushes": 0, "lines": 0}
    funcs = []
    for f in sorted(root.glob("*.js")):
        raw = f.read_text(encoding="utf-8", errors="ignore")
        t = strip(raw)
        totals["lines"] += raw.count("\n") + 1
        totals["var"] += len(re.findall(r"\bvar\s", t))
        totals["== / !="] += len(re.findall(r"(?<![=!<>])[=!]=(?!=)", t))
        totals["else after return"] += len(re.findall(r"\breturn\b[^;{}]*;\s*\}\s*else\b", t))
        totals["index loop"] += len(re.findall(r"for\s*\(\s*(?:var|let)\s+\w+\s*=\s*0\s*;\s*\w+\s*<\s*\w[\w.]*\.length\s*;", t))
        totals["loop that only pushes"] += len(re.findall(r"for\s*\([^)]*\)\s*\{\s*(?:if\s*\([^)]*\)\s*)?\w[\w.]*\.push\([^;]*\);\s*\}", t))
        for m in re.finditer(r"function\s*(\w*)\s*\(([^)]*)\)\s*\{", t):
            start = t.index("{", m.start())
            end = match(t, start, "{", "}")
            body = t[start:end + 1]
            depth = best = 0
            for ch in body:
                depth += ch == "{"
                depth -= ch == "}"
                best = max(best, depth)
            params = [x for x in m.group(2).split(",") if x.strip()]
            funcs.append((t.count("\n", start, end) + 1, best - 1, len(params), m.group(1) or "(anonymous)", f.name))
    print("js lines: %(lines)d | var: %(var)d | == or !=: %(== / !=)d | else after return: %(else after return)d | index loops: %(index loop)d | loops that only push: %(loop that only pushes)d" % totals)
    print("functions: %d | longer than 60 lines: %d | more than 4 parameters: %d | block nesting deeper than 4: %d" % (
        len(funcs), sum(1 for x in funcs if x[0] > 60), sum(1 for x in funcs if x[2] > 4), sum(1 for x in funcs if x[1] > 4)))
    print("longest:", [(n, ln, fn.split("-")[0]) for ln, d, p, n, fn in sorted(funcs, reverse=True)[:8]])
    print("deepest:", [(n, d, fn.split("-")[0]) for ln, d, p, n, fn in sorted(funcs, key=lambda x: -x[1])[:8]])
    print("DONE_JS_PATTERNS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
