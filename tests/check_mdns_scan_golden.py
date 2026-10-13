"""Golden-master test of scan_mdns.mdns_scan with the network parts replaced by in-memory fakes (the zeroconf browse fills `found` and then ends normally, times out, raises ImportError or
another error; a fake logger and a fake mDNS memory record their calls): 1500 generated lists of (type, instance, address, TXT) - user-named and other service types, invalid addresses,
TXT with friendly_name/fn/location_name (empty, slug-like, repeated), model and manufacturer keys, repeated addresses - and a pre-filled `mdns_meta` must give exactly the same names (or
exception), the same `mdns_meta`, AND the same ordered log calls as the code before the function was split. tests/golden/mdns_scan.json keeps one sha1 per case plus a readable sample.
Regenerate only on purpose:  MDNS_SCAN_GOLDEN_UPDATE=1 python tests/check_mdns_scan_golden.py"""
import asyncio
import hashlib
import json
import os
import random
import sys
import tempfile
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()      # never the real folder of the developer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import mdns_listener, scan_mdns  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "mdns_scan.json"
N = 1500
rng = random.Random(30303)
LOG: list = []
SET: dict = {}


class FakeLogger:
    @staticmethod
    def warning(fmt, *args):
        LOG.append(["warning", fmt, repr(args)])

    @staticmethod
    def exception(fmt, *args):
        LOG.append(["exception", fmt, repr(args)])


async def fake_browse(found):
    found.extend(SET["entries"])
    mode = SET["mode"]
    if mode == "timeout":
        await asyncio.sleep(5)
    elif mode == "import":
        raise ImportError("no zeroconf")
    elif mode == "error":
        raise ValueError("boom")


def fake_remember(found):
    LOG.append(["remember_scan", repr(list(found))])
    if SET["remember_fails"]:
        raise RuntimeError("disk")


scan_mdns.logger = FakeLogger
scan_mdns._mdns_browse = fake_browse
scan_mdns._MDNS_BUDGET = 0.05
mdns_listener.remember_scan = fake_remember


def pick(seq):
    return seq[rng.randrange(len(seq))]


STYPES = ["_hap._tcp", "_airplay._tcp", "_sonos._tcp", "_googlecast._tcp", "_companion-link._tcp", "_http._tcp", "_esphomelib._tcp", "_workstation._tcp", "_smb._tcp"]
ADDRS = ["192.168.1.%d" % i for i in range(2, 8)] + ["999.1.1.1", "", "not-an-ip", "10.0.0.1"]
NAMES = ["Salotto", "iPhone di Luca", "esp-1", "", "Printer", "x" * 70, "5c53de3b-esphome"]
VALUES = ["Cucina", "Studio", "", "5c53de3b-esphome", "abcdef12-xyz", "abc-def", "Camera da letto", "A" * 70, "12345-x"]


def txt():
    parts = []
    for key in ("friendly_name", "fn", "location_name", "model", "am", "md", "manufacturer", "mf", "ofn", "other"):
        if rng.random() < 0.25:
            parts.append('"%s=%s"' % (key, pick(VALUES + ["MacBookPro18,1", "Acme"])))
    if rng.random() < 0.05:
        parts.append("fn=Bare")
    rng.shuffle(parts)
    return " ".join(parts)


out = []
for _ in range(N):
    SET["entries"] = [(pick(STYPES), pick(NAMES), pick(ADDRS), txt()) for _ in range(rng.randrange(0, 7))]
    SET["mode"] = pick(["ok", "ok", "ok", "ok", "ok", "timeout", "import", "error", "error"])
    SET["remember_fails"] = rng.random() < 0.15
    scan_mdns.mdns_meta.clear()
    for ip in ("192.168.1.2", "192.168.1.9"):
        if rng.random() < 0.3:
            scan_mdns.mdns_meta[ip] = pick([{"model": "Old", "services": ["_old._tcp"]}, {}, {"manufacturer": "OldCo"}])
    LOG.clear()
    try:
        res = asyncio.run(scan_mdns.mdns_scan())
    except Exception as exc:
        res = ["EXC", type(exc).__name__]
    out.append({"mode": SET["mode"], "n": len(SET["entries"]), "res": res, "meta": json.loads(json.dumps(scan_mdns.mdns_meta)), "log": list(LOG)})


def digest(x):
    return hashlib.sha1(json.dumps(x).encode()).hexdigest()[:20]


mine = json.loads(json.dumps({"digests": [digest(o) for o in out], "sample": out[:30]}, sort_keys=True))
if os.environ.get("MDNS_SCAN_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(mine, sort_keys=True, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want["digests"]) == len(mine["digests"]) == N
for i, (x, y) in enumerate(zip(mine["digests"], want["digests"])):
    assert x == y, "case %d differs: %s" % (i, json.dumps(out[i])[:700])
assert mine["sample"] == want["sample"]
modes = {m: sum(1 for o in out if o["mode"] == m) for m in ("ok", "timeout", "import", "error")}
assert all(v > 60 for v in modes.values()), modes
assert sum(1 for o in out if o["mode"] == "error" and o["n"] and o["res"]) > 20 and sum(1 for o in out if o["mode"] == "error" and not o["res"]) > 20
assert sum(1 for o in out if o["mode"] == "timeout" and o["res"]) > 20
assert sum(1 for o in out if any(l[0] == "exception" for l in o["log"])) > 40 and sum(1 for o in out if any(l[0] == "remember_scan" for l in o["log"])) > 700
assert sum(1 for o in out if isinstance(o["res"], dict) and len(o["res"]) > 2) > 100
assert any(v == "Cucina" for o in out if isinstance(o["res"], dict) for v in o["res"].values())
assert any("services" in m and len(m["services"]) > 1 for o in out for m in o["meta"].values())
assert any("model" in m and "services" in m for o in out for m in o["meta"].values())
print("TUTTO OK")
