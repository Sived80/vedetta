"""The nesting measure of the gate (tools/nesting.py) on known cases, because a metric is tried before it is believed: the first reading of this project counted every `elif` as one more level and gave
74 / 18 / 2 functions instead of 62 / 16 / 1. Also the ratchet rule of the gate: counts can only go down."""
import os
import pathlib
import sys
import textwrap

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import gate_rules  # noqa: E402
import nesting  # noqa: E402


def depth_of(code: str) -> int:
    return max(nesting.function_depths(textwrap.dedent(code)).values())


assert depth_of("def f(x):\n    return x\n") == 0
assert depth_of("def f(x):\n    if x:\n        return 1\n") == 1
# an elif chain is ONE level, however long
assert depth_of("def f(x):\n    if x == 1:\n        pass\n    elif x == 2:\n        pass\n    elif x == 3:\n        pass\n    else:\n        pass\n") == 1
# an `if` inside an else is a deeper block, not an elif (the else has two statements)
assert depth_of("def f(x):\n    if x:\n        pass\n    else:\n        y = 1\n        if y:\n            pass\n") == 2
# stacked blocks add up
assert depth_of("def f(x):\n    for a in x:\n        with a:\n            try:\n                if a:\n                    pass\n            except OSError:\n                pass\n") == 4
# a nested function is measured on its own, not added to the outer one
inner = nesting.function_depths("def outer():\n    def inner():\n        for a in b:\n            if a:\n                pass\n    return inner\n")
assert sorted(inner.values()) == [0, 2], inner
# async blocks and match
assert depth_of("async def f(x):\n    async for a in x:\n        async with a:\n            pass\n") == 2
assert depth_of("def f(x):\n    match x:\n        case 1:\n            if x:\n                pass\n") == 2

# JavaScript: lines indented five levels (ten spaces) or more; comments do not count
js = "function a() {\n  if (x) {\n    for (;;) {\n      while (y) {\n        if (z) {\n          deep();\n        }\n      }\n    }\n  }\n}\n          // a comment at the same indent\n"
assert nesting.js_deep_lines(js) == 1, nesting.js_deep_lines(js)
# the lines of a long string, indented for reading, are not nested code
html = "function a() {\n  return (\n    x +\n          '<div>' +\n          \"<span>\" +\n          `<i>` +\n          + 1\n  );\n}\n"
assert nesting.js_deep_lines(html) == 0, nesting.js_deep_lines(html)

# the ratchet: a count that goes up is a problem, equal or lower is not, a base without the counts is no problem
base = {"deep3": 62, "deep4": 16, "deep5": 1, "js_deep": 6}
assert gate_rules.nesting_problem(base, base) is None
assert gate_rules.nesting_problem({"deep3": 60, "deep4": 15, "deep5": 0, "js_deep": 0}, base) is None
assert "deep4 16 -> 17" in gate_rules.nesting_problem({**base, "deep4": 17}, base)
assert "js_deep 6 -> 7" in gate_rules.nesting_problem({**base, "js_deep": 7}, base)
assert gate_rules.nesting_problem(base, {}) is None and gate_rules.nesting_problem(base, None) is None
assert gate_rules.nesting_problem(base, {"deep4": 20}) is None, "only the counts that the base has are compared"
# the real project, measured now
import pathlib  # noqa: E402
real = nesting.summary(pathlib.Path(__file__).resolve().parent.parent)
assert set(real) == set(gate_rules.NESTING_KEYS) and real["deep5"] <= real["deep4"] <= real["deep3"], real

# the hard limit: a function nested four levels deep or more must be on the list of allowed ones, and an allowed one that is no longer deep must come off the list
import tempfile  # noqa: E402
tree = pathlib.Path(tempfile.mkdtemp())
(tree / "vedetta" / "app").mkdir(parents=True)
DEEP = """def deep(x):
    for a in x:
        with a:
            try:
                if a:
                    pass
            except OSError:
                pass


def flat(x):
    return x
"""
(tree / "vedetta" / "app" / "m.py").write_text(DEEP, encoding="utf-8")
assert nesting.deep_functions(tree) == {"vedetta/app/m.py:deep"}, nesting.deep_functions(tree)
assert gate_rules.deep_problem({"a.py:f"}, {"a.py:f": "why"}) is None
assert "nested more than 3 levels: b.py:g" in gate_rules.deep_problem({"a.py:f", "b.py:g"}, {"a.py:f": "why"})
assert "take them off the list: a.py:f" in gate_rules.deep_problem(set(), {"a.py:f": "why"})
assert gate_rules.deep_problem(set(), {}) is None
assert nesting.deep_functions(pathlib.Path(__file__).resolve().parent.parent) == set(nesting.ALLOWED_DEEP), "the real project: exactly the allowed functions are deep"
assert all(len(why) > 30 for why in nesting.ALLOWED_DEEP.values()), "every exception says why"
print("TUTTO OK", real)
