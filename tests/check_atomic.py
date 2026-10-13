"""The atomic write (app/atomic.py): the content arrives whole; a write that fails (an error, or an interruption such as Ctrl-C) leaves the previous file untouched and no temporary file behind; the temporary
file is made in the folder asked for (default: the folder of the file), with the prefix asked for; the folder is created when it is missing; the newline is the one asked for."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.atomic import write_atomic  # noqa: E402

root = Path(tempfile.mkdtemp())
target = root / "deep" / "er" / "file.json"
write_atomic(target, lambda f: f.write('{"a": 1}'), ".x-")
assert target.read_text(encoding="utf-8") == '{"a": 1}', "content written, missing folders created"
assert [p.name for p in target.parent.iterdir()] == ["file.json"], "no temporary file left"

write_atomic(target, lambda f: f.write("é\n"), ".x-", newline="\n")
assert target.read_bytes() == "é\n".encode("utf-8"), "UTF-8 and the newline asked for"

for error in (ValueError("boom"), KeyboardInterrupt()):
    def broken(f, error=error):
        f.write("half of the new content")
        raise error
    try:
        write_atomic(target, broken, ".x-")
        raise AssertionError("the error was swallowed")
    except type(error):
        pass
    assert target.read_bytes() == "é\n".encode("utf-8"), "the previous file is intact after %r" % error
    assert [p.name for p in target.parent.iterdir()] == ["file.json"], "no temporary file after %r" % error

other = root / "other"
seen = []
write_atomic(target, lambda f: (seen.append([p.name for p in other.iterdir()]), f.write("z"))[1], ".tmpfolder-", folder=other)
assert seen and seen[0][0].startswith(".tmpfolder-") and seen[0][0].endswith(".tmp"), "the temporary file is in the folder asked for, with the prefix: %r" % seen
assert target.read_text(encoding="utf-8") == "z" and list(other.iterdir()) == []
print("TUTTO OK")
