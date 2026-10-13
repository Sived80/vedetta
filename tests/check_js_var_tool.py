"""The tool that turns `var` into `const`/`let` in the JavaScript of the page (tools/js_var_to_let.py) is tested like the code it changes: on small pieces of JavaScript, what must be converted is converted with the
right keyword, and every case in which `let`/`const` could change what the code does is left with `var` (a block, a parameter, a name declared twice, a use before the declaration, a function declared below and
called above, a `for` header, a declarator that is not a plain name); the parts of the page are read as one function, so a `var` of a later part knows the function that opens in an earlier one."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import js_var_to_let as T  # noqa: E402


def run(js: str) -> str:
    changes, _ = T.convert(js)
    return T.apply(js, changes)


def keyword_of(js: str, name: str) -> str:
    out = run(js)
    line = [ln for ln in out.split("\n") if (" " + name + " =") in ln or (" " + name + ";") in ln or (" " + name + ",") in ln][0]
    return line.strip().split(" ")[0]


# never written -> const; written (=, +=, ++, --, for...in) -> let; no value -> let
assert keyword_of("function f() {\n  var a = 1;\n  return a;\n}\n", "a") == "const"
assert keyword_of("function f() {\n  var a = 1;\n  a += 2;\n  return a;\n}\n", "a") == "let"
assert keyword_of("function f() {\n  var a = 0;\n  a++;\n  return a;\n}\n", "a") == "let"
assert keyword_of("function f() {\n  var a;\n  a = 3;\n  return a;\n}\n", "a") == "let"
assert keyword_of("function f(o) {\n  var k;\n  for (k in o) g(k);\n}\n", "k") == "let"
assert keyword_of("function f(o) {\n  var a = o.name;\n  o.name = 2;\n  return a;\n}\n", "a") == "const", "a property with the same name is not the variable"
assert keyword_of("function f() {\n  var s = 'a = b; c = d', t = 2;\n  return s + t;\n}\n", "s") == "const", "text inside a string is not code"
assert keyword_of("function f() {\n  var a = 1, b = 2;\n  b = 3;\n  return a + b;\n}\n", "a") == "let", "one written name makes the whole statement let"

# left alone
for name, js in {
    "block": "function f(c) {\n  if (c) {\n    var a = 1;\n  }\n  return a;\n}\n",
    "parameter": "function f(a) {\n  var a = a || 1;\n  return a;\n}\n",
    "declared twice": "function f() {\n  var a = 1;\n  for (var a = 0; a < 3; a++) {}\n  return a;\n}\n",
    "used before": "function f() {\n  g(a);\n  var a = 1;\n  return a;\n}\n",
    "function below called above": "function f() {\n  init();\n  var cache = {};\n  function init() { if (cache) { cache.x = 1; } }\n  return cache;\n}\n",
    "for header": "function f() {\n  for (var i = 0; i < 3; i++) {}\n}\n",
    "destructuring": "function f(o) {\n  var [a, b] = o;\n  return a + b;\n}\n",
    "outside a function": "var a = 1;\nvar b = a;\n",
    "switch": "function f(x) {\n  switch (x) {\n    case 1:\n      var a = 2;\n      return a;\n  }\n}\n",
}.items():
    assert run(js) == js, name + " must not change"

# the same name in two different functions is two different variables
two = "function f() {\n  var a = 1;\n  return a;\n}\nfunction g() {\n  var a = 2;\n  return a;\n}\n"
assert run(two).count("const a") == 2

# a function inside a function: the inner var is converted for the inner function only
nested = "function f() {\n  var a = 1;\n  function g() {\n    var b = a;\n    return b;\n  }\n  return g();\n}\n"
out = run(nested)
assert "const a = 1" in out and "const b = a" in out

# the parts of the page are one function: the opening and the closing are in different files
part1 = "(function () {\n  \"use strict\";\n  var a = 1;\n"
part2 = "  var b = a + 1;\n  function f() { return b; }\n"
part3 = "  f();\n})();\n"
joined = run(part1 + part2 + part3)
assert "const a = 1" in joined and "const b = a + 1" in joined
alone = run(part2)
assert alone == part2, "a part alone has no function around it: nothing is changed"
print("TUTTO OK")
