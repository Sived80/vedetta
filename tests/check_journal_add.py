"""journal.add on its four ways: an entry is appended to the file; a file over the size limit is rewritten whole (atomically) with the entries in memory; a file whose size cannot be read is appended to; a
write that fails never raises (the log is auxiliary). Written on the code before it was flattened and kept passing after it (differential proof)."""
import itertools
import json
import os
import pathlib
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.storage import journal  # noqa: E402

tmp = pathlib.Path(tempfile.mkdtemp())


def reset(path, limit=400):
    journal.PATH = path
    journal.MAX_ENTRIES = limit
    journal._entries = type(journal._entries)(maxlen=limit)
    journal._loaded = True
    journal._seq = itertools.count(1)


def lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# 1) appended one line per entry, ids in sequence, parameters: numbers stay numbers, the rest becomes text
path = tmp / "a.jsonl"
reset(path)
journal.add("normal", "journal.added", icon="plus-circle", name="TV", n=5, ratio=0.5)
journal.add("detail", "journal.quick")
rows = lines(path)
assert [r["id"] for r in rows] == [1, 2] and [r["key"] for r in rows] == ["journal.added", "journal.quick"]
assert rows[0]["params"] == {"name": "TV", "n": 5, "ratio": 0.5} and rows[0]["icon"] == "plus-circle" and rows[1]["icon"] == "history" and rows[1]["level"] == "detail"
assert rows[0]["ts"] <= rows[1]["ts"]

# 2) the folder is created when it is not there
deep = tmp / "x" / "y" / "b.jsonl"
reset(deep)
journal.add("normal", "journal.added")
assert len(lines(deep)) == 1

# 3) a file over 400 bytes per entry of the limit is rewritten whole with the entries in memory (the old lines are gone)
big = tmp / "c.jsonl"
reset(big, limit=3)
big.write_text("".join(json.dumps({"id": 900 + i, "junk": "x" * 40}) + "\n" for i in range(60)), encoding="utf-8")
assert big.stat().st_size > 400 * 3
used = []
real = journal.write_atomic
journal.write_atomic = lambda *a, **k: (used.append(1), real(*a, **k))[1]
try:
    for i in range(2):
        journal.add("normal", "journal.k", n=i)
finally:
    journal.write_atomic = real
assert used, "the big file must be rewritten atomically"
assert [r["id"] for r in lines(big)] == [1, 2] and all("junk" not in r for r in lines(big)), lines(big)

# 4) the size of the file cannot be read: the entry is appended
class Unreadable(pathlib.Path):
    def stat(self, *args, **kwargs):
        if self.name.endswith(".jsonl"):         # only the file itself: its folder must stay readable
            raise OSError("no stat")
        return super().stat(*args, **kwargs)


(tmp / "d.jsonl").write_text(json.dumps({"id": 900, "key": "journal.old"}) + chr(10), encoding="utf-8")      # a line that is already there: appended to, not rewritten
odd = Unreadable(tmp / "d.jsonl")
reset(odd)
used.clear()
journal.add("normal", "journal.added")
assert [r["id"] for r in lines(tmp / "d.jsonl")] == [900, 1], "the entry must be appended to the file that is already there"

# 5) a write that fails never raises (here the path is a folder), and the entry is still in memory
folder = tmp / "folder.jsonl"
folder.mkdir()
reset(folder)
journal.add("normal", "journal.added")
assert len(journal._entries) == 1
print("TUTTO OK")
