"""A catalog of signatures that cannot be read (missing, not JSON, no «signatures» key) used to empty the recognition without a trace: every device was then «generic» and nobody knew why (finding R4b of the
global review, rule: no empty answer without a trace). Now it is told once in the log, at warning level, and the answer is still an empty catalog (the service goes on). A good catalog says nothing."""
import logging
import os
import sys
import tempfile
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import applog  # noqa: E402
from app.recognition import signatures  # noqa: E402

records: list = []


class Catch(logging.Handler):
    def emit(self, record):
        records.append(record)


applog.logger.addHandler(Catch())
tmp = Path(tempfile.mkdtemp())
real_path = signatures.DATA_PATH


def load_from(path):
    signatures.DATA_PATH = path
    signatures._cache["sigs"] = None
    del records[:]
    result = signatures.load()
    again = signatures.load()
    return result, again


# a good catalog: nothing is said
good, _ = load_from(real_path)
assert good and not [r for r in records if r.levelno >= logging.WARNING], "a good catalog says nothing"

# three ways to be unreadable: an empty catalog, ONE warning (the second load comes from the cache), and the service goes on
(tmp / "broken.json").write_text("{not json", encoding="utf-8")
(tmp / "nokey.json").write_text('{"other": []}', encoding="utf-8")
for path in (tmp / "broken.json", tmp / "nokey.json", tmp / "missing.json"):
    result, again = load_from(path)
    assert result == [] and again == [], path.name
    warnings = [r for r in records if r.levelno == logging.WARNING]
    assert len(warnings) == 1, (path.name, [r.getMessage() for r in records])
    assert "signatures" in warnings[0].getMessage().lower(), warnings[0].getMessage()

signatures.DATA_PATH = real_path
signatures._cache["sigs"] = None
print("TUTTO OK")
