# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""Every link between the public documents goes somewhere: README.md, docs/*.md and the app's DOCS.md/CHANGELOG.md. A relative link must name a
file of the repository, and its #anchor a heading of that file (GitHub's rule: lower case, punctuation dropped, spaces to hyphens). Links to
the web are not fetched here (no network in the tests); images are files too.
    python tests/check_doc_links.py"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = [ROOT / "README.md", ROOT / "SECURITY.md", ROOT / "vedetta" / "DOCS.md", ROOT / "vedetta" / "CHANGELOG.md", *sorted((ROOT / "docs").glob("*.md"))]
LINK = re.compile(r"\]\(([^)\s]+)\)|(?:src|href|srcset)=\"([^\"]+)\"")


def anchors(path: Path) -> set:
    text = path.read_text(encoding="utf-8")
    out = set(re.findall(r'<a (?:name|id)="([^"]+)"', text))           # an anchor written by hand
    for line in text.splitlines():
        m = re.match(r"#+\s+(.*)", line)
        if m:
            heading = re.sub(r"[^\w\- ]", "", m.group(1).strip().lower(), flags=re.UNICODE)
            out.add(heading.replace(" ", "-"))
    return out


failed = []
checked = 0
for doc in DOCS:
    if not doc.exists():
        continue
    text = re.sub(r"```.*?```", "", doc.read_text(encoding="utf-8"), flags=re.S)
    for m in LINK.finditer(text):
        target = m.group(1) or m.group(2)
        if re.match(r"^(https?:|mailto:|data:)", target):
            continue
        checked += 1
        file_part, _, anchor = target.partition("#")
        dest = doc if not file_part else (doc.parent / file_part).resolve()
        if not dest.exists():
            failed.append("%s: %s (no such file)" % (doc.relative_to(ROOT), target))
            continue
        if anchor and dest.suffix == ".md" and anchor.lower() not in anchors(dest):
            failed.append("%s: %s (no such heading)" % (doc.relative_to(ROOT), target))

assert checked > 50, "the links are read (%d)" % checked
if failed:
    print("\n".join(failed))
    print("FAILED: %d" % len(failed))
    sys.exit(1)
print("ALL OK (%d links)" % checked)
