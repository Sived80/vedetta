"""Tiered event log and cancellation of the associative searches."""
import asyncio
import os
import pathlib
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.storage import journal
from app.scan import pipeline  # noqa: E402

journal.PATH = pathlib.Path(tempfile.mkdtemp()) / "journal.jsonl"
journal._entries.clear()
journal._loaded = True
journal.add("normal", "journal.added", icon="plus-circle", name="TV", ip="10.0.0.5")
journal.add("detail", "journal.quick", icon="magnify", seen=20, new=2)
assert [e["key"] for e in journal.entries("normal", 10)] == ["journal.added"]
assert [e["key"] for e in journal.entries("detail", 10)] == ["journal.quick", "journal.added"]
assert journal.entries("min", 10) == []
# Re-read from the file after a restart.
journal._entries.clear()
journal._loaded = False
assert len(journal.entries("detail", 10)) == 2


async def go():
    async def slow():
        await asyncio.sleep(10)
    t = asyncio.create_task(slow())
    pipeline._running["10.0.0.9"] = t
    assert pipeline.cancel_associative(["10.0.0.8"]) == 0
    assert pipeline.cancel_associative(["10.0.0.9"]) == 1
    await asyncio.sleep(0)
    assert t.cancelled() or t.cancelling()

asyncio.run(go())
print("TUTTO OK")
