"""Golden-master test of localapi.parse_esphome_events: 6000 generated texts of server-sent events (pings and other events, data lines with valid JSON with or without a title, a list, a number,
broken JSON, a data line one, two or three lines after the event, blank lines, spaces around, several pings) must give exactly the same answer as the code before the function was split;
digests and a readable sample are stored in tests/golden/esphome_events.json.
Regenerate only on purpose:  ESPHOME_GOLDEN_UPDATE=1 python tests/check_esphome_events_golden.py"""
import hashlib
import json
import os
import random
import sys
import tempfile
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()      # never the real folder of the developer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import localapi  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "esphome_events.json"
N = 6000
rng = random.Random(8080)


def pick(seq):
    return seq[rng.randrange(len(seq))]


PAYLOADS = ['{"title": "kitchen light"}', '{"title": "kitchen light"}', '{"title": "garden"}', '{"title": "kitchen light"}', '{"title": ""}', '{"title": null}', '{"name": "x"}', '[1, 2]', '5', '"text"', '{broken', '', '{"title": "a", "x": 1}', '{"title": 7}']


def make_text():
    lines = []
    for _ in range(rng.randrange(0, 5)):
        kind = pick(["ping", "ping", "ping", "ping", "state", "log", "blank", "data", "noise", "ping "])
        if kind == "ping":
            lines.append(pick(["event: ping", "event: ping", "  event: ping  ", "event:ping"]))
            for _ in range(rng.randrange(1, 4)):
                lines.append(pick(["data: " + pick(PAYLOADS), "data:" + pick(PAYLOADS), "", "id: 1", "retry: 10", "data: " + pick(PAYLOADS), "data: " + pick(PAYLOADS)]))
        elif kind == "ping ":
            lines.append("event: ping x")
        elif kind == "state":
            lines.append("event: state")
            lines.append("data: " + pick(PAYLOADS))
        elif kind == "log":
            lines.append("event: log")
        elif kind == "blank":
            lines.append("")
        elif kind == "data":
            lines.append("data: " + pick(PAYLOADS))
        else:
            lines.append(pick(["hello", "ping", ":comment"]))
    return pick(["\n", "\r\n", "\n", "\r", "\x0c"]).join(lines)


out = [{"text": t, "res": localapi.parse_esphome_events(t)} for t in (make_text() for _ in range(N))]


def digest(x):
    return hashlib.sha1(json.dumps(x, sort_keys=True, default=str).encode()).hexdigest()[:20]


result = {"digests": [digest(o) for o in out], "sample": json.loads(json.dumps(out[:10]))}
if os.environ.get("ESPHOME_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(result, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want["digests"]) == len(result["digests"]) == N
for i, (x, y) in enumerate(zip(result["digests"], want["digests"])):
    assert x == y, "text %d differs: %s" % (i, json.dumps(out[i], default=str)[:500])
assert result["sample"] == want["sample"]
found = sum(1 for o in out if o["res"])
assert found > 700 and N - found > 700, ("scenarios too uniform", found)
assert any("\r\n" in o["text"] and o["res"] for o in out) and any("\r" in o["text"] and "\n" not in o["text"] and o["res"] for o in out)
assert any(o["res"] == {} and '{broken' in o["text"] for o in out)
print("TUTTO OK")
