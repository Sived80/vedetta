"""The pause of the periodic check (app/pause.py): timed and endless pause, survival to a restart, expiry, and a corrupt file."""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import pause as pause_mod  # noqa: E402
from app.storage import settings  # noqa: E402

settings.CONFIG_DIR = Path(tempfile.mkdtemp())
FILE = settings.CONFIG_DIR / "pause.json"

p = pause_mod.Pause()
assert p.remaining() is None and p.total is None and not FILE.exists()

p.start(10)                                            # timed pause: saved, and the page gets its length
assert 595 < p.remaining() <= 600 and p.total == 600.0 and FILE.exists()
again = pause_mod.Pause()                              # a restart finds it again
assert 595 < again.remaining() <= 600 and again.total == 600.0

p.start(0)                                             # endless: no expiry and no length
assert p.remaining() == float("inf") and p.total is None
again = pause_mod.Pause()
assert again.remaining() == float("inf") and again.total is None

p.stop()                                               # resumed: the file goes away
assert p.remaining() is None and not FILE.exists() and pause_mod.Pause().remaining() is None

p.until, p.total = time.time() - 1, 60.0               # a pause that ended is forgotten, with its length
assert p.remaining() is None and p.until is None and p.total is None

FILE.write_text('{"until": %s, "total": 30}' % (time.time() - 5), encoding="utf-8")   # expired on disk: not resumed after a restart
assert pause_mod.Pause().remaining() is None
FILE.write_text("not json", encoding="utf-8")          # corrupt file: active, no error
assert pause_mod.Pause().remaining() is None
print("TUTTO OK")
