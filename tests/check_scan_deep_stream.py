"""Characterisation test of the deep search stream (POST /api/scan/deep, server-sent events) through the real HTTP layer. The searches are replaced by small coroutines that end in every way the
stream has to tell apart: with a result, with an error, cancelled, with an empty result; in different orders and numbers. What the client receives (every event, in order) and what the
route does around it (journal entries, the start and the end of the search activity) is stored in tests/golden/scan_deep_stream.json, written from the code as it was before the waiting for one search
was moved into its own function.
Regenerate only on purpose:  SCAN_DEEP_GOLDEN_UPDATE=1 python tests/check_scan_deep_stream.py"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()      # never the real folder of the developer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.routes import scan_routes  # noqa: E402
from app.scan import pipeline  # noqa: E402
from app.state import state  # noqa: E402
from app.storage import journal  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "scan_deep_stream.json"
LOG: list = []
journal.add = lambda *a, **k: LOG.append(["journal.add", list(a), k])
state.search_started = lambda: LOG.append(["search_started"])
state.search_finished = lambda: LOG.append(["search_finished"])
state.track = lambda fut: LOG.append(["track"])


async def _local(ips):
    return list(ips)


scan_routes.filter_local_ips = _local


TURNS = 40      # the loops of the event loop that one step of delay lasts


def job(kind, i):
    """The search i ends TURNS * (i + 1) turns of the event loop after the start: the order of the answers, and the time the stream has between two of them to do its work, are counted in turns and do not depend on a
    clock (it used to be a pause of 0.02 s times the number, and under load two close pauses could swap)."""
    async def run():
        for _ in range(TURNS * (i + 1)):
            await asyncio.sleep(0)
        if kind == "ok":
            return {"ip": "10.0.0.%d" % i, "scan_info": {"ports": [80, 443][: i % 3]}}
        if kind == "empty":
            return {}
        if kind == "none_info":
            return {"ip": "10.0.0.%d" % i, "scan_info": None}
        if kind == "error":
            raise RuntimeError("boom")
        if kind == "cancelled":
            raise asyncio.CancelledError()
    return run


SCENARIOS = {
    "none": [],
    "one_ok": ["ok"],
    "two_ok": ["ok", "ok"],
    "error_between": ["ok", "error", "ok"],
    "cancelled_between": ["ok", "cancelled", "ok"],
    "all_fail": ["error", "cancelled", "error"],
    "empty_and_none_info": ["empty", "none_info", "ok"],
    "mixed": ["ok", "error", "cancelled", "empty", "ok", "none_info"],
}


def run_scenario(kinds):
    LOG.clear()

    def fake_start(ips, hints):
        LOG.append(["start_associative", list(ips), hints])
        return [asyncio.ensure_future(job(k, i)()) for i, k in enumerate(kinds)]

    pipeline.start_associative = fake_start
    app = FastAPI()
    app.include_router(scan_routes.router)
    with TestClient(app) as client:
        r = client.post("/api/scan/deep", json={"ips": ["10.0.0.%d" % i for i in range(len(kinds))] + ["not an ip"], "hints": {"x": 1}})
    events = [json.loads(line[6:]) for line in r.text.split("\n") if line.startswith("data: ")]
    return {"status": r.status_code, "events": events, "log": json.loads(json.dumps(LOG, default=str))}


got = {name: run_scenario(kinds) for name, kinds in SCENARIOS.items()}
if os.environ.get("SCAN_DEEP_GOLDEN_UPDATE"):
    GOLDEN.parent.mkdir(exist_ok=True)
    GOLDEN.write_text(json.dumps(got, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print("golden written:", {k: len(v["events"]) for k, v in got.items()})
    sys.exit(0)
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
for name in SCENARIOS:
    assert got[name] == want[name], name + ": the stream is not what it was\n" + json.dumps(got[name], indent=1)[:1500]
assert any(e["type"] == "complete" for e in got["mixed"]["events"]) and len(got["mixed"]["events"]) >= 5
print("TUTTO OK")
