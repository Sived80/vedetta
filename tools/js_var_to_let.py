"""`var` -> `const` / `let` in the JavaScript of the page, only where the change cannot alter what the code does. No parser and no library: the text is read with the comments, strings and regular expressions
blanked (tools/loops_js.strip) and the braces are matched.

A `var` is changed when ALL of this holds (anything else is left alone and counted with its reason):
  - it stands directly in the body of a function (not in an if/for/switch/try block: there `let` would shorten its life and a use after the block would break);
  - the declaration is not a `for (var ...)` header and every declarator is a plain name;
  - the name is not a parameter of that function and is declared once in the function (blocks and `for` headers included);
  - the name is not written anywhere in the function BEFORE the declaration, and no function declared in the same body AFTER the declaration is called before it (with `let` that would be a ReferenceError,
    with `var` it was a silent `undefined`);
  - `const` when no name of the statement is ever assigned (=, +=, ++, --, for...in/of target) and every declarator has a value; `let` otherwise.
    python tools/js_var_to_let.py [JS_DIR] [--write]"""
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from loops_js import strip  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent / "vedetta" / "app" / "frontend" / "ha" / "js"
FUNC_HEADER = re.compile(r"function\s*[\w$]*\s*\(([^()]*)\)\s*$")
ASSIGN_TAIL = r"\s*(?:\+\+|--|(?:[-+*/%&|^]|<<|>>>?|\*\*|&&|\|\||\?\?)?=(?!=))"
DECLARATOR = re.compile(r"^\s*([A-Za-z_$][\w$]*)\s*(=|$)", re.S)


def word(name: str) -> str:
    return r"(?<![\w$.])" + re.escape(name) + r"(?![\w$])"


def statement(s: str, start: int):
    """The declarators of the `var` statement that starts at `start`: [(name, has_value)], or None when something is not a plain name; also where it ends."""
    depth, i, n, cut = 0, start + 3, len(s), []
    begin = i
    while i < n:
        c = s[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            if depth == 0:
                break                              # the end of the block: a statement without semicolon
            depth -= 1
        elif depth == 0 and c == ";":
            break
        elif depth == 0 and c == ",":
            cut.append((begin, i))
            begin = i + 1
        i += 1
    cut.append((begin, i))
    out = []
    for a, b in cut:
        m = DECLARATOR.match(s[a:b])
        if not m:
            return None, i
        out.append((m.group(1), m.group(2) == "="))
    return out, i


def convert(text: str):
    """([(position of the var, "const" or "let")], Counter of what was changed and why the rest was not)."""
    s = strip(text)
    stack: list[tuple[int, bool, str]] = []        # (index of the brace, it is the body of a function, its parameters)
    found = []                                      # (position of var, innermost brace, nearest function brace)
    var_at = {m.start() for m in re.finditer(r"\bvar\s", s)}
    pending = sorted(var_at)
    pi = 0
    for i, c in enumerate(s):
        while pi < len(pending) and pending[pi] == i:
            fn = next((b for b in reversed(stack) if b[1]), None)
            found.append((i, stack[-1] if stack else None, fn))
            pi += 1
        if c == "{":
            m = FUNC_HEADER.search(s[max(0, i - 300):i])
            stack.append((i, bool(m), m.group(1) if m else ""))
        elif c == "}" and stack:
            stack.pop()
    ends = {}
    st = []
    for i, c in enumerate(s):                       # the closing brace of every opening brace
        if c == "{":
            st.append(i)
        elif c == "}" and st:
            ends[st.pop()] = i
    declared = Counter()                            # (function brace, name) -> how many declarations
    plans = []
    stats = Counter()
    for pos, inner, fn in found:
        if fn is None:
            stats["outside any function"] += 1
            continue
        fkey = fn[0]
        if re.search(r"for\s*\(\s*$", s[max(0, pos - 20):pos]):
            m = re.match(r"var\s+([\w$]+)", s[pos:])
            declared[(fkey, m.group(1))] += 1 if m else 0
            stats["for header"] += 1
            continue
        names, _end = statement(s, pos)
        if names:
            for name, _ in names:
                declared[(fkey, name)] += 1
        plans.append((pos, inner, fn, names))
    out = []
    for pos, inner, fn, names in plans:
        fkey, params = fn[0], fn[2]
        if names is None:
            stats["not a plain name"] += 1
            continue
        if inner is None or inner[0] != fkey:
            stats["inside a block"] += 1
            continue
        body_start, body_end = fkey + 1, ends.get(fkey, len(s))
        _, stmt_end = statement(s, pos)
        before, after = s[body_start:pos], s[stmt_end:body_end]
        why = None
        later_functions = set(re.findall(r"function\s+([\w$]+)\s*\(", s[stmt_end:body_end]))
        for name, _ in names:
            if re.search(word(name), params):
                why = "a parameter"
            elif declared[(fkey, name)] > 1:
                why = "declared more than once"
            elif re.search(word(name), before):
                why = "used before the declaration"
            elif any(re.search(r"(?<![\w$.])" + re.escape(f) + r"\s*\(", before) for f in later_functions):
                why = "a function declared below is called above"
            if why:
                break
        if why:
            stats[why] += 1
            continue
        written = any(re.search(word(name) + ASSIGN_TAIL, after) or re.search(r"(?:\+\+|--)\s*" + word(name), after)
                      or re.search(r"for\s*\(\s*" + word(name) + r"\s+(?:in|of)\b", after) for name, _ in names)
        keyword = "let" if written or not all(has for _, has in names) else "const"
        stats["-> " + keyword] += 1
        out.append((pos, keyword))
    return out, stats


def apply(text: str, changes) -> str:
    for pos, keyword in sorted(changes, reverse=True):
        text = text[:pos] + keyword + text[pos + 3:]
    return text


def main() -> int:
    """The parts are pieces of ONE function (assets.bundle joins them): they are read together, so that a `var` of one part knows the function that opens in another."""
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    root = Path(args[0]) if args else ROOT
    files = sorted(root.glob("*.js"))
    raws = [f.read_bytes().decode("utf-8") for f in files]
    texts = [r.replace("\r\n", "\n") for r in raws]
    changes, stats = convert("".join(texts))
    print("var declarations: " + " | ".join("%s %d" % (k, v) for k, v in sorted(stats.items())))
    if "--write" in sys.argv:
        start = 0
        for f, raw, text in zip(files, raws, texts):
            mine = [(pos - start, kw) for pos, kw in changes if start <= pos < start + len(text)]
            if mine:
                new = apply(text, mine)
                f.write_bytes((new.replace("\n", "\r\n") if "\r\n" in raw else new).encode("utf-8"))
            start += len(text)
    print("DONE_VAR")
    return 0


if __name__ == "__main__":
    sys.exit(main())
