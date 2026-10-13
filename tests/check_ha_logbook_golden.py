"""Golden-master test of GET /api/ha/logbook through the real HTTP layer: 1500 generated requests - the three levels and unknown ones, limits out of range or not numbers, presence rows of known,
unknown and mobile devices, journal entries important or not, service log entries with and without a time or a level - with the collaborators replaced by recorders must give exactly the answer
(status, body) and every call made (with its arguments), stored in tests/golden/ha_logbook.json, written from the code as it was before api_ha_logbook was split into small functions.
Regenerate only on purpose:  HA_LOGBOOK_GOLDEN_UPDATE=1 python tests/check_ha_logbook_golden.py"""
import hashlib
import json
import os
import random
import sys
import tempfile
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()      # never the real folder of the developer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app import applog  # noqa: E402
from app.ha import ha_data  # noqa: E402
from app.routes import ha as ha_routes  # noqa: E402
from app.state import state  # noqa: E402
from app.storage import journal  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "ha_logbook.json"
N = 1500
rng = random.Random(4242)
LOG: list = []
M: dict = {}
IDS = ["d1", "d2", "d3", "d4"]


def pick(seq):
    return seq[rng.randrange(len(seq))]


def jcopy(x):
    return json.loads(json.dumps(x, default=str))


def recent_presence(n):
    LOG.append(["recent_presence", n])
    return list(M["rows"])


def logbook_entries(rows, devices, cfg):
    LOG.append(["logbook_entries", len(rows)])
    return [{"id": r["id"], "ts": r["ts"], "device_id": r["device_id"], "known": r["known"], "message": "m%s" % r["id"], "level": "min"} for r in rows]


def journal_entries(level, limit):
    LOG.append(["journal.entries", level, limit])
    return list(M["journal"])


def get_entries():
    return list(M["applog"])


ha_data.recent_presence, ha_data.logbook_entries, ha_data.config_map = recent_presence, logbook_entries, lambda: {}
journal.entries = journal_entries
applog.get_entries = get_entries
ha_routes.i18n.use_request = lambda request: None
ha_routes.i18n.t = lambda key, **p: "T:%s:%s" % (key, sorted(p.items()))
app = FastAPI()
app.include_router(ha_routes.router)
client = TestClient(app, raise_server_exceptions=False)


def scenario():
    rows = [{"id": i, "ts": round(rng.uniform(1000, 2000), 2), "device_id": pick(IDS), "known": rng.random() < 0.7} for i in range(rng.randrange(0, 8))]
    jr = [{"id": i, "key": pick(sorted(journal.IMPORTANT)[:3] + ["journal.other", "journal.added"]), "level": pick(["normal", "service"]), "ts": round(rng.uniform(1000, 2000), 2),
           **({"icon": pick(["plus-circle", "eye-off"])} if rng.random() < 0.6 else {}), **({"params": {"name": pick(["A", "B"])}} if rng.random() < 0.5 else {})} for i in range(rng.randrange(0, 6))]
    al = [{**({"ts": pick([0, 0.0, round(rng.uniform(1000, 2000), 3)])} if rng.random() < 0.85 else {}), **({"level": pick(["WARNING", "ERROR", "CRITICAL", "INFO", None])} if rng.random() < 0.8 else {}),
           **({"message": pick(["x", "y z", ""])} if rng.random() < 0.8 else {})} for _ in range(rng.randrange(0, 6))]
    M.clear()
    M.update(rows=rows, journal=jr, applog=al)
    state.devices.clear()
    for i in IDS:
        if rng.random() < 0.8:
            state.devices[i] = {"is_mobile": pick([True, False, 1, 0, None])}
    return rows, jr, al


out = []
for _ in range(N):
    LOG.clear()
    rows, jr, al = scenario()
    level = pick(["min", "normal", "detail", "bogus", "", "min"])
    limit = pick([1, 3, 5, 30, 0, -4, 500, "7", "abc"])
    r = client.get("/api/ha/logbook", params={"level": level, "limit": limit})
    out.append({"req": [level, limit], "data": [rows, jr, al], "status": r.status_code, "body": r.text, "log": jcopy(LOG)})


def digest(x):
    return hashlib.sha1(json.dumps(x, default=str).encode()).hexdigest()[:20]


result = {"digests": [digest(o) for o in out], "sample": jcopy(out[:6])}
if os.environ.get("HA_LOGBOOK_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(result, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want["digests"]) == len(result["digests"]) == N
for i, (x, y) in enumerate(zip(result["digests"], want["digests"])):
    assert x == y, "request %d differs: %s" % (i, json.dumps(out[i], default=str)[:900])
assert result["sample"] == want["sample"]
c = lambda f: sum(1 for o in out if f(o))  # noqa: E731
ev = lambda o: json.loads(o["body"]).get("events", []) if o["status"] == 200 else []  # noqa: E731
stats = {"ok": c(lambda o: o["status"] == 200), "err": c(lambda o: o["status"] != 200), "min": c(lambda o: o["status"] == 200 and json.loads(o["body"])["level"] == "min"),
         "normal": c(lambda o: o["status"] == 200 and json.loads(o["body"])["level"] == "normal"), "detail": c(lambda o: o["status"] == 200 and json.loads(o["body"])["level"] == "detail"),
         "presence": c(lambda o: any(e["kind"] == "presence" for e in ev(o))), "journal": c(lambda o: any(e["id"].startswith("j") for e in ev(o))), "trace": c(lambda o: any(e["id"].startswith("l") for e in ev(o))),
         "alert": c(lambda o: any(e.get("icon") == "alert-circle" for e in ev(o))), "cut": c(lambda o: o["status"] == 200 and len(ev(o)) == o["req"][1] if isinstance(o["req"][1], int) else False),
         "empty": c(lambda o: o["status"] == 200 and not ev(o))}
for key, low in (("ok", 1000), ("err", 50), ("min", 300), ("normal", 150), ("detail", 150), ("presence", 400), ("journal", 400), ("trace", 60), ("alert", 25), ("cut", 100), ("empty", 20)):
    assert stats[key] >= low, ("scenarios too uniform", key, stats)
print("TUTTO OK")
