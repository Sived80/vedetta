"""The tools that rewrite the code (tools/loop_to_pipeline.py, tools/inline_helpers.py, the import pruner of tools/prune_unused_imports.py) are tested like the code they change: each one is run on a small
module written for the purpose; what it must rewrite is rewritten, what it must leave alone is byte for byte the same, and the rewritten module gives the same answers as the original on the same inputs."""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
tmp = Path(tempfile.mkdtemp())


def run(tool, path, *extra):
    r = subprocess.run([sys.executable, str(TOOLS / tool), str(path), *extra], capture_output=True, text=True, cwd=str(ROOT), timeout=120)
    assert r.returncode == 0, (tool, r.stdout[-300:], r.stderr[-300:])
    return r.stdout


def load(path):
    ns = {}
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), ns)
    return ns


# ---------------------------------------------------------------- loops -> pipelines
LOOPS = '''
LIMITS = [(10, "small"), (100, "medium"), (1000, "large")]


def size_of(n):
    for limit, name in LIMITS:
        if n < limit:
            return name
    return "huge"


def has_even(values):
    for v in values:
        if v % 2 == 0:
            return True
    return False


def labels(items):
    out = []
    for i in items:
        if i:
            out.append(str(i).upper())
    return out


def index(words):
    d = {}
    for w in words:
        d[w] = len(w)
    return d


def with_comment(values):
    for v in values:
        # a comment inside: left alone
        if v > 3:
            return v
    return 0


def with_call_default(values, fallback):
    for v in values:
        if v > 3:
            return v
    return fallback()


def with_else(values):
    for v in values:
        if v > 3:
            return v
    else:
        return -1
    return 0


def with_break(values):
    out = []
    for v in values:
        if v > 100:
            break
        out.append(v)
    return out
'''
f = tmp / "loops_case.py"
f.write_text(LOOPS, encoding="utf-8")
before = load(f)
out = run("loop_to_pipeline.py", f, "--write")
after_text = f.read_text(encoding="utf-8")
assert "rewrites written: 4" in out, out
assert "return next((name for limit, name in LIMITS if n < limit)" in after_text and "return any(v % 2 == 0 for v in values)" in after_text
assert 'out = [str(i).upper() for i in items if i]' in after_text and "d = {w: len(w) for w in words}" in after_text
for kept in ("with_comment", "with_call_default", "with_else", "with_break"):          # not touched: their text is the original text
    body = LOOPS[LOOPS.index("def " + kept):].split("\n\n\n")[0]
    assert body in after_text, kept + " was changed"
after = load(f)
for n in (0, 5, 50, 500, 5000):
    assert before["size_of"](n) == after["size_of"](n)
for vals in ([], [1, 3], [1, 2], [7, 2, 9]):
    assert before["has_even"](vals) == after["has_even"](vals)
    assert before["labels"](vals) == after["labels"](vals)
    assert before["with_comment"](vals) == after["with_comment"](vals)
assert before["index"](["a", "bcd"]) == after["index"](["a", "bcd"])

# ---------------------------------------------------------------- unused imports
import prune_unused_imports as prune  # noqa: E402
IMPORTS = "import os, sys\nfrom pathlib import Path, PurePath\nfrom json import loads\nimport re\n\nprint(Path, loads)\n"
g = tmp / "imports_case.py"
g.write_text(IMPORTS, encoding="utf-8")
prune.rewrite(g, {"sys", "PurePath", "re"})
assert g.read_text(encoding="utf-8") == "import os\nfrom pathlib import Path\nfrom json import loads\n\nprint(Path, loads)\n", g.read_text(encoding="utf-8")
prune.rewrite(g, {"loads"})
assert "json" not in g.read_text(encoding="utf-8"), "a statement left empty is deleted"

# ---------------------------------------------------------------- helpers back into their caller
# (the names of the helpers are built here, so that this file does not contain them: the tool counts the places where a name is written in the repository)
P = "_" + "zq9x" + "_"
HELPERS = '''
def _P_plain(a, b):
    return a * 2 + b


def _P_documented(a):
    """The double of a number, named on purpose."""
    return a * 2


def _P_twice_used(a):
    return a + 1


def _P_clash(a):
    return a + OFFSET


OFFSET = 10


def uses_plain(x, y):
    return _P_plain(x, y)


def uses_documented(x):
    return _P_documented(x) + 1


def uses_twice(x):
    return _P_twice_used(x) + _P_twice_used(x + 1)


def uses_clash(x):
    OFFSET = 1000
    return _P_clash(x) + OFFSET


def _P_arg(a):
    return a + 1


def uses_call_argument(x):
    return _P_arg(len(str(x)))
'''.replace("_P_", P)
h = tmp / "helpers_case.py"
h.write_text(HELPERS, encoding="utf-8")
before = load(h)
out = run("inline_helpers.py", h, "--write")
text = h.read_text(encoding="utf-8")
assert P + "plain" not in text, "the helper used once with plain arguments is inlined: " + out
assert "return x * 2 + y" in text, text
assert "def " + P + "documented" in text and "def " + P + "twice_used" in text and "def " + P + "clash" in text, "documented, twice-used and shadowed helpers stay"
assert "def " + P + "arg" in text and P + "arg(len(str(x)))" in text, "a call with an argument that is not plain stays"
after = load(h)
for x in (0, 3, 12):
    for y in (0, 5):
        assert before["uses_plain"](x, y) == after["uses_plain"](x, y)
    assert before["uses_documented"](x) == after["uses_documented"](x)
    assert before["uses_twice"](x) == after["uses_twice"](x)
    assert before["uses_clash"](x) == after["uses_clash"](x)
    assert before["uses_call_argument"](x) == after["uses_call_argument"](x)
print("TUTTO OK")
