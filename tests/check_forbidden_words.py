"""Words that must never appear in what the user sees or in what the product writes (rule of the owner): «riscansione» (and its forms) is said «ricerca approfondita». Found by the global
review: a log message of the nightly maintenance said «da riscansionare». The search covers the code, the page, the language files, the documents and the golden files (a golden that holds the
word would keep it alive). Only the product and its documents are searched: the notes and the tests that name the word to forbid it are outside (this file is skipped by name)."""
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN = re.compile(r"riscansion|riscansiona", re.I)
FOLDERS = ("vedetta", "docs", "tests/golden", "tests/data")
FILES = ("README.md", "CONTRIBUTING.md", "SECURITY.md")
SUFFIXES = {".py", ".js", ".html", ".json", ".md", ".yaml", ".yml", ".txt", ".css", ".sh"}
SELF = {"check_forbidden_words.py"}

hits = []
candidates = [p for folder in FOLDERS for p in (ROOT / folder).rglob("*") if p.is_file()] + [ROOT / f for f in FILES if (ROOT / f).exists()]
for path in candidates:
    if path.suffix.lower() not in SUFFIXES or path.name in SELF or "node_modules" in path.parts or "__pycache__" in path.parts:
        continue
    for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if FORBIDDEN.search(line):
            hits.append(f"{path.relative_to(ROOT).as_posix()}:{number}")
assert not hits, "the forbidden word «riscansione» is in %d places, say «ricerca approfondita»: %s" % (len(hits), ", ".join(hits[:8]))
print("TUTTO OK")
