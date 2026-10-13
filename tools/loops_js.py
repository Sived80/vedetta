"""Inventory of the loops and timers of the web front end (JavaScript), to check that each one ends and to see which ones can cost time in the browser. It reads the text only (comments and strings are
removed first, braces are matched by hand: there is no JavaScript parser in the project and none is added), so it points at places to look at; it proves nothing by itself.
  - `while` / `do` / `for` loops, nested two or more deep, and `while` loops with nothing in the body that can leave them;
  - timers: setInterval without a clearInterval in the same file, setTimeout that schedules the function it runs in (a loop that never stops by itself), requestAnimationFrame the same way;
  - work repeated on every turn of a loop: querySelector(All), innerHTML built with +=, addEventListener inside a loop.
    python tools/loops_js.py [FRONTEND_DIR] [--list]"""
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "vedetta" / "app"


def strip(text: str) -> str:
    """Comments, strings, template literals and regular expressions replaced by spaces (same length, so line numbers stay)."""
    out, i, n = [], 0, len(text)
    prev = ""
    while i < n:
        c = text[i]
        two = text[i:i + 2]
        if two == "//":
            j = text.find("\n", i)
            j = n if j == -1 else j
            out.append(" " * (j - i)); i = j
        elif two == "/*":
            j = text.find("*/", i + 2)
            j = n if j == -1 else j + 2
            out.append("".join(ch if ch == "\n" else " " for ch in text[i:j])); i = j
        elif c in "'\"`":
            q = c
            j = i + 1
            while j < n and text[j] != q:
                j += 2 if text[j] == "\\" else 1
            j = min(j + 1, n)
            out.append("".join(ch if ch == "\n" else " " for ch in text[i:j])); i = j
        elif c == "/" and prev in "(,=:[!&|?{};\n" and two != "/=":
            j = i + 1
            while j < n and text[j] not in "/\n":
                j += 2 if text[j] == "\\" else 1
            j = min(j + 1, n)
            out.append(" " * (j - i)); i = j
        else:
            out.append(c); i += 1
        if out and out[-1].strip():
            prev = out[-1][-1]
    return "".join(out)


def match(text: str, start: int, open_c: str, close_c: str) -> int:
    depth = 0
    for i in range(start, len(text)):
        if text[i] == open_c:
            depth += 1
        elif text[i] == close_c:
            depth -= 1
            if depth == 0:
                return i
    return len(text) - 1


def loops_of(text: str):
    """[(kind, start, end, body)] of the loops: the body is the braces after the head, or the single statement."""
    found = []
    for m in re.finditer(r"\b(while|for)\s*\(|\bdo\s*\{", text):
        kind = m.group(1) or "do"
        if kind == "do":
            b0 = text.index("{", m.start())
            b1 = match(text, b0, "{", "}")
            found.append(("do", m.start(), b1, text[b0:b1 + 1]))
            continue
        p0 = text.index("(", m.start())
        p1 = match(text, p0, "(", ")")
        k = p1 + 1
        while k < len(text) and text[k].isspace():
            k += 1
        if k < len(text) and text[k] == "{":
            b1 = match(text, k, "{", "}")
        else:
            b1 = text.find(";", k)
            b1 = len(text) - 1 if b1 == -1 else b1
        found.append((kind, m.start(), b1, text[k:b1 + 1]))
    return found


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    root = Path(args[0]) if args else ROOT / "frontend"
    show = "--list" in sys.argv
    files = [f for f in sorted(root.rglob("*.js"))] + [f for f in sorted((ROOT / "static").rglob("*.js"))] if root == ROOT / "frontend" and (ROOT / "static").exists() else sorted(root.rglob("*.js"))
    stats, rows = Counter(), []
    for f in files:
        raw = f.read_text(encoding="utf-8", errors="ignore")
        text = strip(raw)
        rel = f.relative_to(ROOT).as_posix() if ROOT in f.parents else f.name
        line = lambda pos: raw.count("\n", 0, pos) + 1  # noqa: E731
        loops = loops_of(text)
        stats["files"] += 1
        stats["lines"] += raw.count("\n") + 1
        for kind, s, e, body in loops:
            stats[kind] += 1
            inner = [(k2, s2, e2, b2) for (k2, s2, e2, b2) in loops if s < s2 and e2 <= e]
            if inner:
                deep = any(s3 > s2 and e3 <= e2 for (_, s2, e2, _) in inner for (_, s3, e3, _) in inner)
                stats["loops three deep" if deep else "loops two deep"] += 1
                rows.append(("three loops deep" if deep else "two loops deep", rel, line(s), kind))
            if kind in ("while", "do") and not re.search(r"\b(break|return|throw)\b", body):
                head = text[s:text.index("{", s)] if "{" in text[s:s + 200] else text[s:s + 60]
                if re.match(r"\s*while\s*\(\s*(true|1)\s*\)", head) or kind == "do":
                    stats["while(true) / do without break, return or throw"] += 1
                    rows.append(("loop that does not leave", rel, line(s), kind))
                else:
                    stats["while without break, return or throw (check the condition changes)"] += 1
                    rows.append(("while with no way out but its condition", rel, line(s), kind))
            if re.search(r"querySelector(All)?\s*\(", body) and kind in ("for", "while"):
                stats["loop that queries the page on every turn"] += 1
                rows.append(("query of the page inside a loop", rel, line(s), kind))
            if re.search(r"innerHTML\s*\+=", body):
                stats["innerHTML += inside a loop (the page is rebuilt on every turn)"] += 1
                rows.append(("innerHTML += inside a loop", rel, line(s), kind))
            if re.search(r"addEventListener\s*\(", body):
                stats["addEventListener inside a loop"] += 1
                rows.append(("addEventListener inside a loop", rel, line(s), kind))
        n_set, n_clear = len(re.findall(r"\bsetInterval\s*\(", text)), len(re.findall(r"\bclearInterval\s*\(", text))
        stats["setInterval"] += n_set
        if n_set and not n_clear:
            stats["file with setInterval and no clearInterval"] += 1
            rows.append(("setInterval never cleared in the file", rel, 0, "timer"))
        for m in re.finditer(r"function\s+(\w+)\s*\([^)]*\)\s*\{", text):
            end = match(text, text.index("{", m.start()), "{", "}")
            body = text[m.end():end]
            if re.search(r"\b(setTimeout|requestAnimationFrame)\s*\(\s*%s\b" % re.escape(m.group(1)), body):
                stats["function that schedules itself again (setTimeout / requestAnimationFrame)"] += 1
                rows.append(("function that schedules itself again", rel, line(m.start()), m.group(1)))
        stats["addEventListener"] += len(re.findall(r"\baddEventListener\s*\(", text))
        stats["removeEventListener"] += len(re.findall(r"\bremoveEventListener\s*\(", text))
    print("js files: %d (%d lines) | for %d, while %d, do %d | addEventListener %d, removeEventListener %d, setInterval %d" % (
        stats["files"], stats["lines"], stats["for"], stats["while"], stats["do"], stats["addEventListener"], stats["removeEventListener"], stats["setInterval"]))
    for k in ("loops two deep", "loops three deep", "while(true) / do without break, return or throw", "while without break, return or throw (check the condition changes)",
              "loop that queries the page on every turn", "innerHTML += inside a loop (the page is rebuilt on every turn)", "addEventListener inside a loop",
              "file with setInterval and no clearInterval", "function that schedules itself again (setTimeout / requestAnimationFrame)"):
        print("  %-72s %d" % (k, stats[k]))
    if show:
        for kind, rel, ln, what in sorted(rows):
            print("  %-42s %s:%s %s" % (kind, rel, ln, what))
    print("DONE_LOOPS_JS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
