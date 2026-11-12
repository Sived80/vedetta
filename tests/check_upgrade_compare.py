"""The comparison of the update test (tools/upgrade_check.py): going forward tables and files may appear; nothing that was there may disappear, shrink or change, the database must be ok. Pure function, no folders.
Step P4: a table born with the new code must survive the way back (the old code ignores it, never empties it), and after the third step (forward again) every card -> MAC link belongs to a card
that is there with the same seq (none inherited by a card added again with the same id) and none moved to another MAC."""
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

# step P4: the tables born going forward, after the way back
start = after()
fwd = after(tables={"scans": 10, "latency": 500, "card_mac": 4})
assert uc.compare_born(start, fwd, after(tables={"scans": 10, "latency": 500, "card_mac": 4}), "back") == []
assert uc.compare_born(start, fwd, after(tables={"scans": 10, "latency": 500, "card_mac": 5}), "back") == [], "more rows are fine"
assert [p for p in uc.compare_born(start, fwd, after(tables={"scans": 10, "latency": 500, "card_mac": 2}), "back") if "card_mac" in p and "lost rows" in p]
assert [p for p in uc.compare_born(start, fwd, after(), "back") if "card_mac" in p and "gone" in p]
# ... and the links after forward again
fl = {"links": {"a": [1, "02:00:00:00:00:01"], "b": [2, "02:00:00:00:00:02"]}, "seqs": {"a": 1, "b": 2}}
assert uc.compare_links(fl, {"links": {"a": [1, "02:00:00:00:00:01"]}, "seqs": {"a": 1}}, "again") == [], "a link gone with its card is fine"
assert uc.compare_links(fl, {"links": {"a": [1, "02:00:00:00:00:01"], "b": [5, "02:00:00:00:00:02"]}, "seqs": {"a": 1, "b": 5}}, "again") == [], "a card added again, judged anew"
assert [p for p in uc.compare_links(fl, {"links": {"a": [1, "02:00:00:00:00:01"], "b": [2, "02:00:00:00:00:02"]}, "seqs": {"a": 1, "b": 5}}, "again") if "b" in p and "inherited" in p]
assert [p for p in uc.compare_links(fl, {"links": {"a": [1, "02:00:00:00:00:09"]}, "seqs": {"a": 1}}, "again") if "moved" in p]
assert [p for p in uc.compare_links(fl, {"links": {"c": [3, "02:00:00:00:00:03"]}, "seqs": {}}, "again") if "c" in p and "no card" in p]
assert [p for p in uc.compare_links(fl, {"links": {"a": [1, "02:00:00:00:00:01"], "c": [3, "02:00:00:00:00:01"]}, "seqs": {"a": 1, "c": 3}}, "again") if "two cards" in p]
assert uc.compare_links({}, {}, "again") == [], "an old version on both sides: no links to compare"
print("TUTTO OK")
