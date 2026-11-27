# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""R8: the deep search of "Add all" can be silent for minutes (2 heavy scans at a time, a pilot test that runs alone, 150 s per slow device). A proxy may drop
a silent stream and the page then waited for ever. The stream now sends a comment line (": keepalive") whenever no device has ended for KEEPALIVE_S, so the
connection stays alive and the page can tell a lost stream (nothing at all for new-devices.js STALL_MS) from a slow search. The events themselves do not
change (tests/check_scan_deep_stream.py), and a client that goes away still stops the stream.
    python tests/check_scan_deep_keepalive.py"""
import asyncio
import json
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()      # never the real folder of the developer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app import sse  # noqa: E402
from app.routes import scan_routes  # noqa: E402
from app.scan import pipeline  # noqa: E402
from app.state import state  # noqa: E402
from app.storage import journal  # noqa: E402

journal.add = lambda *a, **k: None
state.search_started = state.search_finished = lambda: None
state.track = lambda fut: None


async def _local(ips):
    return list(ips)


scan_routes.registry.allowed = _local


def slow_start(ips, hints):
    async def one(ip, delay):
        await asyncio.sleep(delay)
        return {"ip": ip, "scan_info": {}}
    return [asyncio.ensure_future(one(ip, 0.45 * (i + 1))) for i, ip in enumerate(ips)]


pipeline.start_associative = slow_start
scan_routes.KEEPALIVE_S = 0.1
app = FastAPI()
app.include_router(scan_routes.router)
with TestClient(app) as client:
    r = client.post("/api/scan/deep", json={"ips": ["192.0.2.31", "192.0.2.32"]})
lines = [line for line in r.text.split("\n") if line]
keep = [line for line in lines if line.startswith(":")]
events = [json.loads(line[6:]) for line in lines if line.startswith("data: ")]
assert r.status_code == 200, r.text
assert len(keep) >= 4 and all(line == ": keepalive" for line in keep), "a silent search sends keep-alive lines: %s" % lines
assert [e["type"] for e in events] == ["total", "progress", "progress", "complete"], events
assert [x["ip"] for x in events[-1]["results"]] == ["192.0.2.31", "192.0.2.32"], events[-1]
first_progress = lines.index(next(line for line in lines if '"progress"' in line))
assert any(line.startswith(":") for line in lines[1:first_progress]), "the keep-alive comes while the first device is still being searched: %s" % lines


# with_keepalive alone: items in order, nothing added when the items come quickly, and closing the stream closes the inner one
async def quick():
    for i in range(3):
        yield "item %d" % i


async def closing():
    got = []
    closed = asyncio.Event()

    async def inner():
        try:
            yield "a"
            await asyncio.sleep(10)
            yield "b"
        finally:
            closed.set()
    stream = sse.with_keepalive(inner(), 0.05)
    got.append(await stream.__anext__())
    got.append(await stream.__anext__())
    await stream.aclose()
    await asyncio.wait_for(closed.wait(), 1)
    return got


async def collect(gen):
    return [x async for x in gen]


assert asyncio.run(collect(sse.with_keepalive(quick(), 5))) == ["item 0", "item 1", "item 2"]
assert asyncio.run(closing()) == ["a", ": keepalive\n\n"], "the keep-alive comes between items, and closing the stream ends the inner one"
print("ALL OK")
