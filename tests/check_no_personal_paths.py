"""No file tracked by Git may carry the name of the person who develops it, or of the company (a stray local file, a measurement database, a
path in a log): the repository is public. Every tracked file is read as bytes, so binary files count too."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# written in pieces, so that this very file does not contain them
FORBIDDEN = ("Devis" + "Mutton", "ZEE" + "TREE", "devis" + "mutton")

try:
    files = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout.decode("utf-8").split("\0")
except (OSError, subprocess.CalledProcessError):
    print("SKIP: git is not available")
    sys.exit(0)

bad = []
for rel in filter(None, files):
    path = ROOT / rel
    if not path.is_file() or path.stat().st_size > 20_000_000:
        continue
    data = path.read_bytes()
    for word in FORBIDDEN:
        if word.encode() in data or word.encode("utf-16-le") in data:
            bad.append((rel, word[:3] + "…"))
assert not bad, "files that carry a personal name or a company name: " + ", ".join(f"{r} ({w})" for r, w in bad[:8])
print("TUTTO OK")
