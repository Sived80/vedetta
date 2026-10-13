"""How deeply the blocks of a function are nested (if / for / while / try / with / match), and how deep the lines of the JavaScript are indented. Used by the gate (tools/gate.py) as a ratchet.
A function body is level 0; a block inside it is level 1, a block inside that one level 2... An `elif` is the same level as its `if` (it is a second branch, not a deeper block); a nested def, class or
lambda is measured on its own. Pure functions and a small summary; no library (rule: no new dependency for what 40 lines can do)."""
import ast
from pathlib import Path

BLOCKS = (ast.If, ast.For, ast.While, ast.Try, ast.With, ast.AsyncFor, ast.AsyncWith, ast.Match)
SEPARATE = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
JS_UNIT = 2          # the front end is indented with two spaces
JS_LIMIT = 5         # levels (of two spaces) from which a line counts as deep


def _depth(node, level: int, is_elif: bool = False) -> int:
    here = level if is_elif or not isinstance(node, BLOCKS) else level + 1
    deepest = here
    for field, value in ast.iter_fields(node):
        children = value if isinstance(value, list) else [value]
        for child in children:
            if not isinstance(child, ast.AST) or isinstance(child, SEPARATE):
                continue
            elif_branch = isinstance(node, ast.If) and field == "orelse" and len(children) == 1 and isinstance(child, ast.If)
            deepest = max(deepest, _depth(child, here, elif_branch))
    return deepest


def function_depths(source: str) -> dict[str, int]:
    """{line:name -> depth} of every function of a Python source."""
    return {f"{node.lineno}:{node.name}": _depth(node, 0) - 0 for node in ast.walk(ast.parse(source)) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def js_deep_lines(text: str) -> int:
    """How many lines of a JavaScript source are indented JS_LIMIT levels or more (comment lines are not counted)."""
    count = 0
    for line in text.splitlines():
        stripped = line.lstrip(" ")
        # comment lines and the continuation lines of a long string (they begin with a quote or a plus sign) are indented for reading, they are not nested code
        if stripped and not stripped.startswith(("//", "*", "/*", "'", '"', "`", "+")) and (len(line) - len(stripped)) // JS_UNIT >= JS_LIMIT:
            count += 1
    return count


def summary(root: Path) -> dict:
    """{"deep3": functions at depth >= 3, "deep4": >= 4, "deep5": >= 5, "js_deep": JavaScript lines at JS_LIMIT levels} of vedetta/app."""
    depths = []
    for path in (root / "vedetta" / "app").rglob("*.py"):
        if "__pycache__" not in path.parts:
            depths += function_depths(path.read_text(encoding="utf-8")).values()
    js = sum(js_deep_lines(p.read_text(encoding="utf-8")) for p in (root / "vedetta" / "app" / "frontend").rglob("*.js") if "node_modules" not in p.parts)
    return {"deep3": sum(d >= 3 for d in depths), "deep4": sum(d >= 4 for d in depths), "deep5": sum(d >= 5 for d in depths), "js_deep": js}


DEEP_FROM = 4          # a function nested this deep (or more) must be on the list below

# The only functions allowed to be nested four levels deep, and why (review of 2026-10-11: «da non toccare», rule never to risk commanding a device). The list can only shrink.
ALLOWED_DEEP = {
    "vedetta/app/scan/wol.py:send": "Wake-on-LAN sends a packet to a device: it is a command, so it is left as it is (a test of the bytes sent comes before any change)",
    "vedetta/app/export/export_mask.py:_repair_file": "part of the double check of the masking of an export (privacy promise); the module was not covered by the global review",
    "vedetta/app/export/export_mask.py:_fix_databases": "part of the double check of the masking of an export (privacy promise); the module was not covered by the global review",
}


def deep_functions(root: Path) -> set[str]:
    """«path:name» of every function of vedetta/app nested DEEP_FROM levels deep or more (path from the root of the repository)."""
    found = set()
    for path in (root / "vedetta" / "app").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        name = path.relative_to(root).as_posix()
        for key, depth in function_depths(path.read_text(encoding="utf-8")).items():
            if depth >= DEEP_FROM:
                found.add(f"{name}:{key.split(':', 1)[1]}")
    return found
