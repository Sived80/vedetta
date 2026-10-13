"""tools/unctx.py (takes the `ctx` container out of a function cut into steps): on small modules written like the splitter writes them, the transformed
module must give exactly the same results as the original for many inputs (sync and async, values passed on and changed, a dict changed in place, an
augmented assignment, a value set only on some paths, a closure that reads), keep the comments of the steps, drop the unused import, and REFUSE what it cannot
do safely (an early exit, ctx used as a whole, a name that would clash, a read of something never set, a closure that assigns, a comment inside the parent)."""
import asyncio
import importlib.util
import os
import random
import sys
import types

spec = importlib.util.spec_from_file_location("unctx", os.path.join(os.path.dirname(__file__), "..", "tools", "unctx.py"))
unctx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(unctx)

SYNC = '''"""Toy."""
from types import SimpleNamespace


def _first(ctx):
    # the total starts from the base
    ctx.total = ctx.base * 2
    ctx.items = []
    ctx.log = {"steps": 1}
    if ctx.base > 5:
        ctx.big = True


def _second(ctx):
    for v in ctx.values:
        ctx.items.append(v + ctx.total)
    ctx.total += len(ctx.items)      # augmented
    ctx.log["steps"] = 2
    pick = lambda x: x + ctx.total   # a closure that only reads
    ctx.extra = pick(1)


def _third(ctx) -> dict:
    return {"total": ctx.total, "items": ctx.items, "log": ctx.log, "extra": ctx.extra, "big": ctx.big if getattr_big(ctx.base) else False}


def getattr_big(n):
    return n > 5


def compute(base, values, unused=None):
    """Doc."""
    ctx = SimpleNamespace(base=base, values=values)
    _first(ctx)
    _second(ctx)
    return _third(ctx)
'''

ASYNC = '''from types import SimpleNamespace


async def _fetch(ctx):
    ctx.data = await ctx.getter(ctx.key)
    ctx.count = 1


async def _use(ctx):
    ctx.count += 1
    return {"data": ctx.data, "count": ctx.count, "key": ctx.key}


async def run(key, getter):
    ctx = SimpleNamespace(key=key, getter=getter)
    await _fetch(ctx)
    return await _use(ctx)
'''

RENAMED = '''from types import SimpleNamespace


def _one(ctx):
    ctx.x = ctx.a + 1


def _two(ctx):
    return ctx.x * ctx.b


def f(a, b=3):
    ctx = SimpleNamespace(a=a, b=b + 1)
    _one(ctx)
    return _two(ctx)
'''

NONE_LAST = '''from types import SimpleNamespace


def _put(ctx):
    ctx.box.append(ctx.n)
    ctx.k = ctx.n + 1


def _put_again(ctx):
    ctx.box.append(ctx.k)


def f(box, n):
    ctx = SimpleNamespace(box=box, n=n)
    _put(ctx)
    _put_again(ctx)
'''

KEEP_OLD = '''from types import SimpleNamespace


def _start(ctx):
    ctx.kind = "generic"
    ctx.extra = {}
    ctx.count = 0


def _maybe_change(ctx):
    if ctx.flag:
        ctx.kind = "special"
        ctx.extra = {"why": ctx.flag}
    if ctx.flag == 2:
        ctx.count += 5
        ctx.late = "L"


def _finish(ctx):
    return {"kind": ctx.kind, "extra": ctx.extra, "count": ctx.count, "late": ctx.late if ctx.flag == 2 else None}


def f(flag):
    ctx = SimpleNamespace(flag=flag)
    _start(ctx)
    _maybe_change(ctx)
    return _finish(ctx)
'''

EARLY = '''from types import SimpleNamespace


def _guard(ctx):
    if ctx.n < 0:
        return {"error": "negative", "n": ctx.n}
    ctx.half = ctx.n // 2
    ctx.tag = "even" if ctx.n % 2 == 0 else "odd"


def _build(ctx):
    if ctx.half > 100:
        return {
            "error": "big",
            "half": ctx.half,
        }
    ctx.out = [ctx.half] * 2


def _done(ctx) -> dict:
    return {"half": ctx.half, "tag": ctx.tag, "out": ctx.out}


def f(n):
    ctx = SimpleNamespace(n=n)
    _result = _guard(ctx)
    if _result is not None:
        return _result
    _result = _build(ctx)
    if _result is not None:
        return _result
    return _done(ctx)
'''

EARLY_NO_OUTS = '''from types import SimpleNamespace


def _check(ctx):
    if not ctx.items:
        return {"empty": True}


def _sum(ctx) -> dict:
    return {"empty": False, "total": sum(ctx.items)}


def f(items):
    ctx = SimpleNamespace(items=items)
    _result = _check(ctx)
    if _result is not None:
        return _result
    return _sum(ctx)
'''

CLASH = '''from types import SimpleNamespace


def _one(ctx):
    items = [1, 2, 3]
    ctx.items = [i * ctx.k for i in items]


def _two(ctx):
    return sum(ctx.items)


def f(k):
    ctx = SimpleNamespace(k=k)
    _one(ctx)
    return _two(ctx)
'''

REFUSED = {
    "closure sees a later change": '''from types import SimpleNamespace


def _one(ctx):
    ctx.x = 1
    ctx.show = lambda: ctx.x


def _two(ctx):
    ctx.x = 2
    return ctx.show()


def f(a):
    ctx = SimpleNamespace(a=a)
    _one(ctx)
    return _two(ctx)
''',
    "early exit returning None": '''from types import SimpleNamespace


def _one(ctx):
    if ctx.a:
        return None
    ctx.x = 2


def _two(ctx):
    return ctx.x


def f(a):
    ctx = SimpleNamespace(a=a)
    _result = _one(ctx)
    if _result is not None:
        return _result
    return _two(ctx)
''',
    "early exit": '''from types import SimpleNamespace


def _one(ctx):
    if ctx.a:
        return 1
    ctx.x = 2


def _two(ctx):
    return ctx.x


def f(a):
    ctx = SimpleNamespace(a=a)
    _one(ctx)
    return _two(ctx)
''',
    "ctx as a whole": '''from types import SimpleNamespace


def _one(ctx):
    helper(ctx)


def _two(ctx):
    return 1


def helper(c):
    pass


def f(a):
    ctx = SimpleNamespace(a=a)
    _one(ctx)
    return _two(ctx)
''',
    "clash with a name already ending in an underscore": '''from types import SimpleNamespace


def _one(ctx):
    x = 5
    x_ = 6
    ctx.x = x + x_


def _two(ctx):
    return ctx.x


def f(a):
    ctx = SimpleNamespace(a=a)
    _one(ctx)
    return _two(ctx)
''',
    "read of nothing": '''from types import SimpleNamespace


def _one(ctx):
    ctx.y = 1


def _two(ctx):
    return ctx.never


def f(a):
    ctx = SimpleNamespace(a=a)
    _one(ctx)
    return _two(ctx)
''',
    "closure assigns": '''from types import SimpleNamespace


def _one(ctx):
    def inner():
        ctx.z = 1
    inner()


def _two(ctx):
    return ctx.z


def f(a):
    ctx = SimpleNamespace(a=a)
    _one(ctx)
    return _two(ctx)
''',
    "comment in parent": '''from types import SimpleNamespace


def _one(ctx):
    ctx.x = ctx.a


def _two(ctx):
    return ctx.x


def f(a):
    ctx = SimpleNamespace(a=a)
    _one(ctx)
    # a comment between steps
    return _two(ctx)
''',
}


def load(src: str) -> types.ModuleType:
    mod = types.ModuleType("toy")
    exec(compile(src, "toy", "exec"), mod.__dict__)
    return mod


rng = random.Random(99)

# --- sync: same results on many inputs
new = unctx.transform(SYNC, "compute")
assert "SimpleNamespace" not in new and "ctx" not in new.replace("# ", ""), new
assert "# the total starts from the base" in new and "# augmented" in new and "# a closure that only reads" in new      # the comments stay
assert "big = None" in new, new                      # set on some paths only: starts unset-safe
old_m, new_m = load(SYNC), load(new)
for _ in range(200):
    base, values = rng.randrange(0, 12), [rng.randrange(0, 9) for _ in range(rng.randrange(0, 5))]
    assert old_m.compute(base, list(values)) == new_m.compute(base, list(values)), (base, values)

# --- async
new = unctx.transform(ASYNC, "run")
assert "await _fetch(" in new and "SimpleNamespace" not in new and "ctx" not in new, new
old_m, new_m = load(ASYNC), load(new)


async def getter(k):
    return k * 2


for key in range(20):
    assert asyncio.run(old_m.run(key, getter)) == asyncio.run(new_m.run(key, getter))

# --- an initial value that is an expression (not the same name)
new = unctx.transform(RENAMED, "f")
assert "b = b + 1" in new, new
old_m, new_m = load(RENAMED), load(new)
for a in range(10):
    assert old_m.f(a) == new_m.f(a) and old_m.f(a, 7) == new_m.f(a, 7)

# --- the last step returns nothing: the parent does not return either
new = unctx.transform(NONE_LAST, "f")
assert "return" not in new.split("def f(")[1], new
old_m, new_m = load(NONE_LAST), load(new)
for n in range(10):
    b1, b2 = [], []
    assert old_m.f(b1, n) == new_m.f(b2, n) is None and b1 == b2 == [n, n + 1]

# --- a value set only on some paths keeps what an earlier step gave it on the others (the bug the pipeline test found)
new = unctx.transform(KEEP_OLD, "f")
old_m, new_m = load(KEEP_OLD), load(new)
for flag in (0, 1, 2, None, 3):
    assert old_m.f(flag) == new_m.f(flag), (flag, old_m.f(flag), new_m.f(flag))
assert new_m.f(0)["kind"] == "generic" and new_m.f(2)["count"] == 5 and new_m.f(1)["extra"] == {"why": 1}
assert "kind = None" not in new and "count = None" not in new and "late = None" in new, new       # only what no earlier step ever set starts as None

# --- an early exit: the step answers (result or None, values to pass on); the parent checks and goes on
new = unctx.transform(EARLY, "f")
old_m, new_m = load(EARLY), load(new)
for n in range(-3, 260):
    assert old_m.f(n) == new_m.f(n), (n, old_m.f(n), new_m.f(n))
assert "_result, half, tag = _guard(" in new and "return None, half, tag" in new and ")," in new.replace(" ", ""), new
new = unctx.transform(EARLY_NO_OUTS, "f")
old_m, new_m = load(EARLY_NO_OUTS), load(new)
for items in ([], [1], [1, 2, 3]):
    assert old_m.f(items) == new_m.f(items)

# --- a name the step also uses for something else: renamed with a trailing underscore everywhere, same results
new = unctx.transform(CLASH, "f")
old_m, new_m = load(CLASH), load(new)
assert "items_" in new, new
for k in range(5):
    assert old_m.f(k) == new_m.f(k)

# --- a two-level container (a wrapper step that makes its own namespace over the outer one) is merged, then the container is taken out
TWO_LEVELS = '''from types import SimpleNamespace


def _start(ctx):
    ctx.total = ctx.a * 2
    ctx.name = "n"


def _w_one(ctx):
    ctx.tmp = ctx.ctx.total + 1
    ctx.ctx.name = ctx.ctx.name + "!"


def _w_two(ctx):
    ctx.ctx.total += ctx.tmp


def _wrapper(ctx):
    ctx = SimpleNamespace(ctx=ctx)
    _w_one(ctx)
    _w_two(ctx)


def _end(ctx) -> dict:
    return {"total": ctx.total, "name": ctx.name}


def P(a):
    ctx = SimpleNamespace(a=a)
    _start(ctx)
    _wrapper(ctx)
    return _end(ctx)
'''
flat = unctx.flatten(TWO_LEVELS, "P", ["_wrapper"])
assert "_wrapper" not in flat and "ctx.ctx" not in flat and "_w_one(ctx)" in flat, flat
new = unctx.transform(flat, "P")
assert "ctx" not in new.replace("# ", ""), new
old_m, new_m = load(TWO_LEVELS), load(new)
for a in range(-3, 12):
    assert old_m.P(a) == new_m.P(a)
CLASH_LEVELS = TWO_LEVELS.replace("ctx.tmp = ctx.ctx.total + 1", "ctx.total = ctx.ctx.total + 1").replace("+= ctx.tmp", "+= ctx.total")
try:
    unctx.flatten(CLASH_LEVELS, "P", ["_wrapper"])
    raise AssertionError("an inner name equal to an outer one was not refused")
except unctx.Refuse:
    pass

# --- what it must refuse
for label, src in REFUSED.items():
    try:
        unctx.transform(src, "f")
    except unctx.Refuse:
        continue
    raise AssertionError(f"not refused: {label}")
print("TUTTO OK")
