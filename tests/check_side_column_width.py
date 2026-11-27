# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The side column of the wide layout (the Network card, the last 12 hours, the log) is wide enough for the tiles of 1.0.1: one tile per
network, two boxes with a label and a value each. At 380 px the tile had about 210 px and its texts were cut (the user, 20/11); at 440 px
it has about 270. The narrow layout (one column) does not change.
    python tests/check_side_column_width.py"""
import os
import re
import sys

css = open(os.path.join(os.path.dirname(__file__), "..", "vedetta", "app", "frontend", "ha", "css", "10-base.css"), encoding="utf-8").read()
m = re.search(r"\.view \{[^}]*grid-template-columns: minmax\((\d+)px, (\d+)px\) minmax\(0, 1fr\)", css)
ok = bool(m) and int(m.group(1)) >= 300 and int(m.group(2)) >= 440
print(("ok: " if ok else "FAILED: ") + "side column from %s to %s px (at least 440 at most)" % (m.group(1) if m else "?", m.group(2) if m else "?"))
narrow = "html.is-narrow .view { grid-template-columns: minmax(0, 1fr); }" in css
print(("ok: " if narrow else "FAILED: ") + "the narrow layout stays one column")
print("ALL OK" if ok and narrow else "FAILED")
sys.exit(0 if ok and narrow else 1)
