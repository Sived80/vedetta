# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""Adds the one-line SPDX license header to every first-party source file: GPL-3.0-only, with the additional terms (GPL-3.0 section 7) in NOTICE.
Re-runnable: a file that already has the line is left as it is, so it can run again after any merge. A shebang, a Python encoding line, an HTML
doctype and a CSS @charset stay first; the line ends of the file (LF or CRLF) are kept. tests/check_license_headers.py fails while a file lacks it.
    python -B tools/add_license_headers.py           add the missing headers and list the files changed
    python -B tools/add_license_headers.py --check   only list the files without it (exit 1 if any)"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

TEXT = "SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE"
ROOT = Path(__file__).resolve().parent.parent

# The comment of each kind of source file ({} is TEXT). Every other kind is skipped: .json (data, locales, packages: JSON has no comments), .md
# (documentation), .svg/.png/.ico (images), .txt (data: the IEEE vendor list, the pinned requirements), .pub (a key), dotfiles and tools/coveragerc
# (settings of the tools), LICENSE, NOTICE, VERSION.
STYLES = {".py": "# {}", ".sh": "# {}", ".yaml": "# {}", ".yml": "# {}", ".toml": "# {}", "Dockerfile": "# {}",
          ".js": "// {}", ".mjs": "// {}", ".css": "/* {} */", ".html": "<!-- {} -->"}

# Files and folders of those kinds that are not first-party source code, with the reason.
SKIP = {
    "tests/golden/": "written by the tests and compared byte for byte (generated)",
    "node_modules/": "third-party packages (npm), not part of the repository",
    "vedetta/app/static/ha/icons.js": "path data of Material Design Icons (Apache-2.0, see THIRD_PARTY_NOTICES.md)",
    "vedetta/translations/": "texts of the options shown by Home Assistant: translations, like the locales JSON",
}

# The lines that must stay before the header: a shebang, then (Python) an encoding declaration; a doctype; a CSS @charset.
_FIRST = {".py": (r"#!", r"[ \t\f]*#.*?coding[:=]"), ".sh": (r"#!",), ".html": (r"(?i)<!doctype",), ".css": (r"@charset",)}


def kind(path):
    """The key of STYLES for this file, or None."""
    return "Dockerfile" if path.name == "Dockerfile" else (path.suffix if path.suffix in STYLES else None)


def skipped(rel):
    """The reason this path (relative, with /) is skipped, or None."""
    for key, why in SKIP.items():
        if rel == key or (key.endswith("/") and (rel.startswith(key) or "/" + key in "/" + rel)):
            return why
    return None


def source_files(root=ROOT):
    """The first-party source files: tracked or new (not ignored) in git, of a kind in STYLES, not skipped, not empty."""
    out = subprocess.run([shutil.which("git") or "git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=root, capture_output=True, check=True).stdout  # noqa: S603 (fixed arguments)
    files = []
    for rel in sorted(set(out.decode("utf-8").split("\0")) - {""}):
        path = root / rel
        if kind(path) and not skipped(rel) and path.is_file() and path.stat().st_size > 0:
            files.append(path)
    return files


def has_header(path):
    """True when the line is in the first five lines of the file."""
    with open(path, encoding="utf-8", errors="replace") as f:
        return any(TEXT in f.readline() for _ in range(5))


def with_header(text, key):
    """The text with the header added (the same text if it has it already)."""
    if TEXT in "".join(text.splitlines(True)[:5]):
        return text
    nl = "\r\n" if "\r\n" in text else "\n"
    bom = "﻿" if text.startswith("﻿") else ""
    lines = text[len(bom):].splitlines(True)
    at = 0
    for pattern in _FIRST.get(key, ()):
        if at < len(lines) and re.match(pattern, lines[at]):
            at += 1
    if at and not lines[at - 1].endswith(("\n", "\r")):
        lines[at - 1] += nl
    lines.insert(at, STYLES[key].format(TEXT) + nl)
    return bom + "".join(lines)


def main(argv):
    check = "--check" in argv
    changed = []
    for path in source_files():
        if has_header(path):
            continue
        changed.append(path.relative_to(ROOT).as_posix())
        if not check:
            text = path.read_bytes().decode("utf-8")
            path.write_bytes(with_header(text, kind(path)).encode("utf-8"))
    for rel in changed:
        print(("missing: " if check else "added: ") + rel)
    print("%d file(s) %s" % (len(changed), "without the header" if check else "changed"))
    return 1 if check and changed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
