"""The comparison of the update test (tools/upgrade_check.py): going forward tables and files may appear; nothing that was there may disappear, shrink or change, the database must be ok. Pure function, no folders."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import upgrade_check as uc  # noqa: E402

before = {"integrity": "ok", "tables": {"scans": 10, "latency": 500}, "devices": {"a": {"ip": "10.0.0.2", "name": "Lamp", "type_user": "iot"}}, "files": ["devices.yaml", "settings.json"]}


def after(**changes):
    out = {"integrity": "ok", "tables": dict(before["tables"]), "devices": {k: dict(v) for k, v in before["devices"].items()}, "files": list(before["files"])}
    out.update(changes)
    return out


assert uc.compare(before, after(), "forward") == []
assert uc.compare(before, after(tables={"scans": 10, "latency": 500, "ip_mac": 0}, files=["devices.yaml", "settings.json", "analysis_since.json"]), "forward") == [], "new tables and files are fine"
assert uc.compare(before, after(tables={"scans": 11, "latency": 900}), "forward") == [], "more rows are fine"
assert uc.compare(before, after(integrity="database disk image is malformed"), "forward") != []
assert [p for p in uc.compare(before, after(tables={"scans": 10}), "forward") if "latency" in p and "gone" in p]
assert [p for p in uc.compare(before, after(tables={"scans": 9, "latency": 500}), "back") if "lost rows" in p and "back" in p]
assert [p for p in uc.compare(before, after(devices={}), "forward") if "gone" in p]
assert [p for p in uc.compare(before, after(devices={"a": {"ip": "10.0.0.2", "name": "Lamp 2", "type_user": "iot"}}), "forward") if "changed" in p]
assert [p for p in uc.compare(before, after(files=["devices.yaml"]), "back") if "settings.json" in p]
print("TUTTO OK")
