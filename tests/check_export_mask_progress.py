"""The masking (step 2 of the export for the developer) can take minutes on a small box: the window must see it move. The engine says how
many files are masked out of how many, the job keeps the latest count while the step runs and the snapshot the window polls carries it;
the next step clears it. Invented names and addresses, no network."""
import json
import os
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.export import export_engine as E, export_jobs as J  # noqa: E402
from app.storage import devices_config  # noqa: E402
from app import paths  # noqa: E402
from app.storage import history as history_mod  # noqa: E402
from app.storage.history import History  # noqa: E402
from app.state import state  # noqa: E402

tmp = Path(tempfile.mkdtemp())
paths.DATA_DIR = tmp
devices_config.DEVICES_PATH = tmp / "devices.yaml"
(tmp / "devices.yaml").write_text(yaml.safe_dump({"devices": [{"id": "d1", "ip": "192.0.2.20", "adapter": "ping", "name": "Lab Sensor"}]}), encoding="utf-8")
(tmp / "settings.json").write_text(json.dumps({"x": 1}), encoding="utf-8")
(tmp / "dashboard.log").write_text("2026-10-07T10:00:00+02:00\tINFO\tLab Sensor 192.0.2.20\n", encoding="utf-8")
history_mod.history = History(tmp / "vedetta.db")
state.devices.clear()
state.devices["d1"] = {"id": "d1", "ip": "192.0.2.20", "mac": "02:00:00:00:00:20", "name": "Lab Sensor", "extra": {}, "scanned_ports": [], "online": True}

steps, parts = [], []
p = E.prepare("dev", None, None, progress=lambda s: steps.append((s, len(parts))), part=lambda done, total: parts.append((done, total)))
try:
    total = len(p.files)
    assert total > 3, p.files.keys()
    at_mask = dict(steps)["mask"]
    assert parts[at_mask:at_mask + 1] == [(0, total)], ("the count starts with the step", parts[:3], total)
    assert parts[-1] == (total, total) and [d for d, _ in parts] == list(range(total + 1)), parts
    assert all(t == total for _, t in parts)
finally:
    p.close()

# "me" masks nothing: no count
parts.clear()
E.prepare("me", None, None, part=lambda done, total: parts.append((done, total))).close()
assert parts == []

# the job keeps the count of the running step; the snapshot carries it; the next step clears it
job = J.Job("dev", None, None)
job.note("mask")
assert J.snapshot(job)["part"] is None
job.part(3, 12)
assert J.snapshot(job)["part"] == {"done": 3, "total": 12}
job.note("check")
assert J.snapshot(job)["part"] is None

print("OK export mask progress")
