# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The rotated logs (dashboard.log.1 .. .3, written by the RotatingFileHandler of applog) follow the chosen period like dashboard.log: the
lines outside it are left out. Without a period they are cut to their tail like the main log. Invented lines only, no network."""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.export import export_gather as G, export_zip as legacy  # noqa: E402

tmp = Path(tempfile.mkdtemp())
now = datetime.now(timezone.utc).astimezone()
old = (now - timedelta(days=5)).isoformat(timespec="seconds")
new = (now - timedelta(hours=2)).isoformat(timespec="seconds")
text = f"{old}\tINFO\tfive days ago\n{new}\tINFO\ttwo hours ago\n"
for name in ("dashboard.log", "dashboard.log.1", "dashboard.log.3"):
    (tmp / name).write_text(text, encoding="utf-8")

since, until = (now - timedelta(days=1)).timestamp(), now.timestamp()
p = G.Prepared("me")
p.since, p.until = since, until
for name in ("dashboard.log", "dashboard.log.1", "dashboard.log.3"):
    G._collect_data_file(p, tmp / name)
for name in ("dashboard.log", "dashboard.log.1", "dashboard.log.3"):
    kept = p.files[f"data/{name}"][1]
    assert "two hours ago" in kept, (name, kept)
    assert "five days ago" not in kept, (name, "a line outside the period is in the export", kept)
p.close()

# without a period: the tail only, like the main log
big = "".join(f"{new}\tINFO\tline {i:07d}\n" for i in range(legacy.MAX_LOG_BYTES // 30 + 1000))
(tmp / "dashboard.log.2").write_text(big, encoding="utf-8")
p = G.Prepared("me")
G._collect_data_file(p, tmp / "dashboard.log.2")
assert len(p.files["data/dashboard.log.2"][1].encode()) <= legacy.MAX_LOG_BYTES, "a rotated log is copied whole without a period"
p.close()

# a file that only looks like one is left as it is
(tmp / "notes.log.bak").write_text(text, encoding="utf-8")
p = G.Prepared("me")
p.since, p.until = since, until
G._collect_data_file(p, tmp / "notes.log.bak")
assert p.files["data/notes.log.bak"][1] == (tmp / "notes.log.bak").read_bytes().decode()
p.close()

print("OK export rotated logs")
