"""The shared, lazy reader of the kernel tables (app/procfs.py): the lines of a file or nothing, never an error, one line at a time, and the first time a path cannot be read it is told at debug level, once
per path (rule of the global review: no `except` that gives an empty answer without a trace)."""
import logging
import os
import sys
import tempfile
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import applog, procfs  # noqa: E402

tmp = Path(tempfile.mkdtemp())
records: list = []


class Catch(logging.Handler):
    def emit(self, record):
        records.append(record)


applog.logger.setLevel(logging.DEBUG)
applog.logger.addHandler(Catch())

good = tmp / "table"
good.write_bytes(b"HEAD a b\nx 1 2\n\ny 3 4\n")
assert list(procfs.lines(good)) == ["HEAD a b\n", "x 1 2\n", "\n", "y 3 4\n"]
assert list(procfs.table(good)) == [["x", "1", "2"], [], ["y", "3", "4"]], "the header is skipped, an empty line is an empty row"
assert list(procfs.table(good, header=2)) == [[], ["y", "3", "4"]] and next(procfs.table(good, header=0)) == ["HEAD", "a", "b"]
assert not records, "a readable file says nothing"

gone = tmp / "missing"
assert list(procfs.lines(gone)) == [] and list(procfs.table(gone)) == []
assert list(procfs.lines(gone)) == [] and list(procfs.table(gone)) == []
assert len(records) == 1 and "missing" in records[0].getMessage() and records[0].levelno == logging.DEBUG, [r.getMessage() for r in records]
assert list(procfs.lines(tmp / "other")) == [] and len(records) == 2, "another path is told on its own"

binary = tmp / "binary"
binary.write_bytes(b"ok\n\xff\nend\n")
try:
    list(procfs.lines(binary))
    raise AssertionError("strict decoding must raise")
except ValueError:
    pass
assert list(procfs.lines(binary, errors="ignore")) == ["ok\n", "\n", "end\n"], "ignore drops the bad bytes"
assert list(procfs.lines(tmp)) == [], "a folder is not a file: an OSError on every system, never an exception out of the reader"

# lazy: a caller that stops at the first line it wants never reads the rest, so a bad byte after it does not matter
late = tmp / "late"
late.write_bytes(b"first\nsecond\n" + b"x" * 20000 + b"\n\xff\n")
assert next(procfs.lines(late)) == "first\n", "the first line is there even though the file ends with a bad byte"
print("TUTTO OK")
