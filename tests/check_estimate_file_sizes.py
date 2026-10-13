"""The part of the size estimate of an export that comes from files (export_estimate._add_log_and_data_file_sizes): every line of the log that starts with a time is counted at its day (its length plus the line
end), the settings files of the data folder (.json and .yaml, not the database) are added to the fixed part, a missing log or folder adds nothing, a log that cannot be read adds nothing. Written on the code
before it was flattened and kept passing after it (differential proof)."""
import os
import sys
import tempfile
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.export import export_estimate as ee  # noqa: E402

tmp = Path(tempfile.mkdtemp())


def run(log_path, data_dir, base=10):
    seen: list = []
    result = ee._add_log_and_data_file_sizes(log_path, base, data_dir, None, lambda ts, size: seen.append((ts, size)))
    return result, seen


LINE1 = "2026-10-11T08:00:00+00:00\tINFO\tstart"
LINE2 = "2026-10-11T09:30:00Z\tERROR\tboom"
log = tmp / "dashboard.log"
log.write_text("\n".join([LINE1, "a line with no time", LINE2, "", "2026-13-45T99:00:00\tINFO\tbad date"]) + "\n", encoding="utf-8")

data = tmp / "data"
data.mkdir()
(data / "devices.yaml").write_bytes(b"x" * 100)
(data / "settings.json").write_bytes(b"y" * 50)
(data / "vedetta.db").write_bytes(b"z" * 1000)
(data / "vedetta.db-wal").write_bytes(b"z" * 1000)
(data / "notes.txt").write_bytes(b"n" * 7)
(data / "other.db").write_bytes(b"q" * 3)          # a database that is not the main one: not a settings file either
(data / "folder.json").mkdir()

# the lines that begin with a valid time are counted with their line end; the file sizes are added to the base
result, seen = run(log, data)
assert [size for _, size in seen] == [len(LINE1) + 1, len(LINE2) + 1], seen
assert all(ts is not None for ts, _ in seen) and seen[0][0] < seen[1][0]
assert result == 10 + 100 + 50, "yaml and json files only, no database, no other extension, no folder: %s" % result

# no log, no data folder: nothing added
assert run(tmp / "none.log", tmp / "none") == (10, [])
assert run(tmp / "none.log", data)[0] == 160 and run(tmp / "none.log", data)[1] == []
assert run(log, tmp / "none")[0] == 10 and len(run(log, tmp / "none")[1]) == 2

# a log that cannot be read (here a folder with that name) adds nothing and does not stop the files
folder_log = tmp / "folder.log"
folder_log.mkdir()
assert run(folder_log, data) == (160, [])

# a log with a byte that is not UTF-8 is still counted (the bad byte is replaced)
bad = tmp / "bad.log"
bad.write_bytes(b"2026-10-11T08:00:00+00:00\tINFO\tx\xff\n")
assert len(run(bad, tmp / "none")[1]) == 1
print("TUTTO OK")
