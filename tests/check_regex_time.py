"""No regular expression of the app can be made slow by what a device sends (ReDoS: a pattern with nested repetition that backtracks
for ever on a crafted text). Every compiled pattern found in the modules of the app is run on texts as long as the longest that is
kept from the network (scan_common.clean_text: 2048 characters for a TXT record), built to make backtracking explode; each run must
end within a small time. A new pattern is checked by itself: nothing to register."""
import importlib
import pkgutil
import re
import sys
import time
import types

sys.path.insert(0, ".")
try:
    import app.applog  # noqa: F401
except Exception:
    stub = types.ModuleType("app.applog")
    import logging
    stub.logger = logging.getLogger("dashboard")
    sys.modules["app.applog"] = stub

import app

N = 2048
LIMIT_S = 0.25          # far above a normal run (well under a millisecond), far below a catastrophic one (seconds to hours)
TEXTS = [ch * N for ch in "a0 .-_:/\\%x"] + [ch * (N - 1) + "!" for ch in "a0 .-_"] + \
        [("ab" * N)[:N], ("a." * N)[:N], ("a-" * N)[:N], ("1." * N)[:N], ("a " * N)[:N] + "\x00", ("aA0" * N)[:N] + "\n",
         "<" * (N // 2) + ">" * (N // 2), "(" * (N // 2) + "x", ("ab:" * N)[:N] + "#"]

patterns = {}
skipped = []
for mod in pkgutil.walk_packages(app.__path__, "app."):
    try:
        m = importlib.import_module(mod.name)
    except Exception as exc:          # a module that needs the container (a binary, a path): its patterns are not reachable here
        skipped.append("%s (%s)" % (mod.name, type(exc).__name__))
        continue
    for name, value in vars(m).items():
        if isinstance(value, re.Pattern) and isinstance(value.pattern, str):
            patterns.setdefault(value.pattern, (value, "%s.%s" % (mod.name, name)))

# the patterns written in place (re.search(r"...", text)): read from the source, they are compiled the same way
import ast
from pathlib import Path
_RE_FUNCS = {"compile", "search", "match", "fullmatch", "sub", "subn", "findall", "finditer", "split"}
for f in sorted(Path(app.__path__[0]).rglob("*.py")):
    for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in _RE_FUNCS
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "re" and node.args
                and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
            flags = 0
            for kw in node.keywords:
                if kw.arg == "flags" and isinstance(kw.value, ast.Attribute) and kw.value.attr in ("I", "IGNORECASE"):
                    flags = re.IGNORECASE
            patterns.setdefault(node.args[0].value, (re.compile(node.args[0].value, flags), "%s:%d" % (f.relative_to(Path(app.__path__[0]).parent).as_posix(), node.lineno)))

# the patterns of the signatures (data/signatures.json, "re"): they are applied to what the devices say, like the others
import json
def _signature_res(obj, where):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "re" and isinstance(v, str):
                patterns.setdefault(v, (re.compile(v, re.IGNORECASE), where))
            else:
                _signature_res(v, where)
    elif isinstance(obj, list):
        for v in obj:
            _signature_res(v, where)
_signature_res(json.loads((Path(app.__path__[0]) / "data" / "signatures.json").read_text(encoding="utf-8")), "data/signatures.json")

slow = []
def _trial(rx, text) -> float:
    t0 = time.perf_counter()
    rx.search(text)
    if rx.groups == 0:
        rx.sub("", text)
    return time.perf_counter() - t0


# short texts first (16 to 28 characters, with the same ending): an exponential pattern doubles its time with each character and
# is caught there (seconds at 28) without hanging the test; only then the long text, for the polynomial ones
for rx, where in patterns.values():
    for text in TEXTS:
        trials = [text[:n - 1] + text[-1] for n in (16, 20, 24, 28)] + [text]
        took = next((t for t in map(lambda x: _trial(rx, x), trials) if t > LIMIT_S), None)
        if took is not None:
            slow.append("%s %.2fs on %r..." % (where, took, text[:12]))
            break

print("patterns checked:", len(patterns), "| modules not importable here:", len(skipped))
for s in skipped:
    print("  skipped", s)
assert len(patterns) > 60, "too few patterns found: the walk of the modules is broken"
assert not slow, "slow patterns:\n" + "\n".join(slow)
print("TUTTO OK")
