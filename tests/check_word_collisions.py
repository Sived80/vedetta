"""The matrix of the words that are both the name of a maker and a word of function (tools/word_collisions.py): found in the data files, decided one by one in tests/data/word_collisions.json.
  - every collision has a decision (a new brand or word that collides makes someone decide), and no decision outlives its collision;
  - every "different" collision (a homonym: the word of function is not what the maker makes) is fenced: the fence "dual" must be a maker of the role dual in data/brands.json, the role that keeps its name out of
    the words of function (tests/check_dual_maker_words.py shows it works for every dual maker);
  - there is at least one homonym, or the matrix would prove nothing."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import word_collisions as wc  # noqa: E402

# the helpers, on a made-up case: a collision with no decision, a decision with no collision
assert wc.undecided({"x": 1, "y": 2}, {"y": {}}) == ["x"] and wc.stale({"x": 1}, {"x": {}, "z": {}}) == ["z"]
assert wc._norm("Home-Assistant!") == "home assistant"

found, decided = wc.collisions(), wc.decisions()
assert len(found) >= 20, "the data files no longer give collisions: %s" % sorted(found)
assert not wc.undecided(found, decided), "collisions without a decision (add them to tests/data/word_collisions.json): %s" % wc.undecided(found, decided)
assert not wc.stale(found, decided), "decisions of collisions that no longer exist: %s" % wc.stale(found, decided)
for name, row in decided.items():
    assert row.get("meaning") in ("same", "multi", "different"), (name, row)
    assert row.get("note"), "a decision says why: %s" % name

dual = set(json.loads((wc.DATA / "brands.json").read_text(encoding="utf-8"))["vendor_roles"]["dual"])
different = {name: row for name, row in decided.items() if row["meaning"] == "different"}
assert different, "no homonym in the data: the matrix would prove nothing"
for name, row in different.items():
    assert row.get("fence") == "dual" and name in dual, "the homonym %s is not fenced by the role dual of data/brands.json: %s" % (name, row)
print("TUTTO OK", {m: sum(1 for r in decided.values() if r["meaning"] == m) for m in ("same", "multi", "different")})
