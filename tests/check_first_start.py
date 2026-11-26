"""When Vedetta first started on this installation (storage/firststart.py): written once in the data folder and then only read; an installation that already
has history (an update from an older version) takes the date of its first event, so the notice of the first hours does not appear to people who have used
it for weeks; a file that cannot be read is written again. The summary says until when the notice of the first 48 hours may appear (None after)."""
import asyncio
import json
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.storage import firststart  # noqa: E402

H = 3600
assert not firststart.PATH.exists()
asked = []


def older():
    asked.append(1)
    return None


# a new installation: the first start is now, written once
assert firststart.first_start(older, now=1000.0) == 1000.0
assert json.loads(firststart.PATH.read_text(encoding="utf-8"))["at"] == 1000.0
assert asked == [1]
assert firststart.first_start(older, now=9999.0) == 1000.0 and asked == [1], "kept: neither the history nor the clock is asked again"
firststart._at = None
assert firststart.first_start(older, now=9999.0) == 1000.0 and asked == [1], "read back from the file (a restart)"

# an update of an older installation: the date of its first event, not today
firststart.PATH.unlink()
firststart._at = None
assert firststart.first_start(lambda: 500.0, now=1000.0 + 30 * 24 * H) == 500.0
firststart._at = None
firststart.PATH.write_text("not json", encoding="utf-8")
assert firststart.first_start(lambda: None, now=2000.0) == 2000.0, "a damaged file is written again"
firststart._at = None
assert firststart.first_start(lambda: None, now=3000.0) == 2000.0

# the 48 hours of the notice
assert firststart.learning_until(1000.0, now=1000.0) == 1000.0 + 48 * H
assert firststart.learning_until(1000.0, now=1000.0 + 47 * H) == 1000.0 + 48 * H
assert firststart.learning_until(1000.0, now=1000.0 + 48 * H) is None
assert firststart.learning_until(1000.0, now=1000.0 + 90 * 24 * H) is None

# what the page learns (summary): until when, or None
from app.routes import ha as routes_ha  # noqa: E402
import time  # noqa: E402
firststart._at = time.time() - H
until = asyncio.run(routes_ha._learning_until())
assert until is not None and abs(until - (firststart._at + 48 * H)) < 1, until
firststart._at = time.time() - 49 * H
assert asyncio.run(routes_ha._learning_until()) is None
print("ALL OK")
