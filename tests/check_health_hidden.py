"""The findings a person chose to hide (storage/health_hidden.py): kept on the server so every browser agrees, validated, capped, survive a restart, a broken file counts as empty."""
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.storage import health_hidden as hh  # noqa: E402

assert hh.load() == [], "nothing hidden at the start"
assert hh.apply(hide=["a|1", "b|2"], show=[]) == ["a|1", "b|2"]
assert hh.apply(hide=["a|1", "c|3"], show=["b|2"]) == ["a|1", "c|3"], "no duplicates; show removes"
hh._cache = None
assert hh.load() == ["a|1", "c|3"], "read back from the file"

# bad input is ignored, never stored
assert hh.apply(hide=["", "x" * 201, 5, None, {"a": 1}], show=[]) == ["a|1", "c|3"]

# the list is capped: the oldest choice goes first
many = ["id%d" % i for i in range(hh.MAX_HIDDEN + 20)]
out = hh.apply(hide=many, show=[])
assert len(out) == hh.MAX_HIDDEN and out[-1] == many[-1] and "a|1" not in out

# a broken file counts as empty
hh.PATH.write_text("{not json", encoding="utf-8")
hh._cache = None
assert hh.load() == []
hh.PATH.write_text('{"hidden": "oops"}', encoding="utf-8")
hh._cache = None
assert hh.load() == []
print("TUTTO OK")
