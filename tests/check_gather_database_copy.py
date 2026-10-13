"""The copy of the database for the export (export_gather._gather_database_copy): no database = nothing; a small one is copied with the sqlite backup (a consistent copy of a database that is in use) and
registered; a period cuts the copy; a database over the size limit is left out with a note unless a period is given; a database that cannot be copied or cut leaves a note and no file. Written on the
code before it was flattened and kept passing after it (differential proof)."""
import os
import sqlite3
import sys
import tempfile
import types
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.export import export_gather as eg  # noqa: E402

CUT: list = []
eg._period_db = lambda copy, since, until: CUT.append((Path(copy).name, since, until))


def run(data_dir: Path, since=None, until=None, limit=None):
    scratch = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)       # a failed copy leaves its connections open (the old code; fixed in its own step)
    p = types.SimpleNamespace(manifest={"notes": []}, since=since, until=until, tmp=scratch, files={})
    del CUT[:]
    saved = eg.legacy.MAX_DB_BYTES
    if limit is not None:
        eg.legacy.MAX_DB_BYTES = limit
    try:
        eg._gather_database_copy(p, data_dir)
    finally:
        eg.legacy.MAX_DB_BYTES = saved
    return p


def make_db(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "vedetta.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE t (a INTEGER)")
    con.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(50)])
    con.commit()
    con.close()
    return path


root = Path(tempfile.mkdtemp())

# 1) no database: nothing
p = run(root / "empty")
assert p.files == {} and p.manifest["notes"] == [] and not CUT

# 2) a small database is copied (the copy has the same rows) and registered; no period = not cut
db = make_db(root / "a")
p = run(root / "a")
kind, copy = p.files["data/vedetta.db"]
assert kind == "db" and Path(copy).parent == Path(p.tmp.name) and Path(copy).name == "vedetta.db"
con = sqlite3.connect(copy)
assert con.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 50
con.close()
assert p.manifest["notes"] == [] and not CUT

# 3) with a period the copy is cut (the original is not touched)
p = run(root / "a", since=100, until=200)
assert CUT == [("vedetta.db", 100, 200)] and "data/vedetta.db" in p.files

# 4) over the size limit: left out with a note, unless a period is given
size = db.stat().st_size
p = run(root / "a", limit=size - 1)
assert p.files == {} and p.manifest["notes"] == [f"vedetta.db not included ({size} bytes)"], p.manifest
p = run(root / "a", since=100, until=200, limit=size - 1)
assert "data/vedetta.db" in p.files and p.manifest["notes"] == [], "with a period the size limit does not apply"

# 5) a file that is not a database: a note, no file
bad = root / "b"
bad.mkdir()
(bad / "vedetta.db").write_bytes(b"this is not a database" * 100)
p = run(bad)
assert p.files == {} and len(p.manifest["notes"]) == 1 and p.manifest["notes"][0].startswith("vedetta.db: "), p.manifest

# 6) the cut fails: a note, and the copy is not registered
eg._period_db = lambda copy, since, until: (_ for _ in ()).throw(RuntimeError("boom"))
p = run(root / "a", since=100, until=200)
assert p.files == {} and p.manifest["notes"] == ["vedetta.db: RuntimeError('boom')"], p.manifest
# 7) every connection that was opened is closed, also when the copy fails (a connection left open locks the file on Windows)
class Tracked:
    opened: list = []

    def __init__(self, con):
        self.con, self.closed = con, False
        Tracked.opened.append(self)

    def backup(self, other):
        return self.con.backup(other.con)

    def close(self):
        self.closed = True
        self.con.close()


real_connect = eg.sqlite3.connect
eg.sqlite3.connect = lambda *a, **k: Tracked(real_connect(*a, **k))
try:
    for folder in (root / "a", bad):
        del Tracked.opened[:]
        run(folder)
        assert len(Tracked.opened) == 2 and all(c.closed for c in Tracked.opened), "a connection was left open (%s)" % folder.name
finally:
    eg.sqlite3.connect = real_connect
print("TUTTO OK")
