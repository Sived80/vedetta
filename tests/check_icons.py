"""Every icon the page asks for by name exists in icons.js (a missing one silently falls back to a generic icon:
the (i) of the certainty rows showed a device icon for that reason)."""
import re
import sys
from pathlib import Path

static = Path(__file__).resolve().parent.parent / "vedetta" / "app" / "static" / "ha"
icons = (static / "icons.js").read_text(encoding="utf-8")
known = set(re.findall(r'^\s*"([a-z0-9-]+)":\s*"M', icons, re.M))
assert len(known) > 100, len(known)
missing = {}
sys.path.insert(0, str(static.parents[2]))
from app import assets  # noqa: E402
for name in ("ha.js",):
    src = assets.bundle("ha/" + name)
    for icon in sorted(set(re.findall(r'\bicon\("([a-z0-9-]+)"\)', src))):
        if icon not in known:
            missing.setdefault(name, []).append(icon)
assert not missing, f"icons used but not in icons.js: {missing}"
print("TUTTO OK")
