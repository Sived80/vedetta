"""Golden-master test of devices_config.add_devices (adds the devices found by a scan to devices.yaml, skipping addresses already present and making identifiers unique):
1500 generated runs on a temporary folder - file missing, empty, with a list of devices (some without id), a devices key that is null, a file that is a list; new devices with and
without id, repeated addresses and identifiers, port 0/None, adapter, name, scan_info and name_source present, empty or falsy, a device without address (KeyError) - must give exactly
the returned list (or the exception) AND the final text of the file (or its absence) stored in tests/golden/devices_add.json, written from the code as it was before the function was
split (digest per case plus a readable sample).
Regenerate only on purpose:  DEVICES_ADD_GOLDEN_UPDATE=1 python tests/check_devices_add_golden.py"""
import hashlib
import json
import os
import random
import shutil
import sys
import tempfile
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()      # never the real folder of the developer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.storage import devices_config  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "devices_add.json"
N = 1500
rng = random.Random(8642)
BASE = Path(tempfile.mkdtemp())


def pick(seq):
    return seq[rng.randrange(len(seq))]


IPS = ["192.168.1.%d" % i for i in (1, 2, 3, 4, 5, 6, 7, 8, 9)] + ["10.0.0.9"]
IDS = ["scan-192-168-1-1", "scan-192-168-1-2", "dev-a", "dev-a-2", "dev-b", "", None, "scan-192-168-1-3-2"] + ["dev-a"] * 3
NAMES = ["Camera", "", None, "Lampada", 0]
INFOS = [None, "", {"mac": "aa:bb"}, [], {}, "open 80"]
SOURCES = [None, "", "scan", "dhcp", 0]


def existing_entry():
    e = {"ip": pick(IPS)} if rng.random() < 0.96 else {}
    if rng.random() < 0.93 and "ip" in e:
        e["id"] = pick(["scan-%s" % e["ip"].replace(".", "-"), "dev-a", "dev-a-2", "dev-b", "x"])
    elif "ip" not in e:
        e["id"] = "noip"

    if rng.random() < 0.3:
        e["name"] = "Old"
    return e


def new_device():
    d = {}
    if rng.random() < 0.97:
        d["ip"] = pick(IPS)
    if rng.random() < 0.6:
        d["id"] = pick(IDS)
    if rng.random() < 0.4:
        d["port"] = pick([80, 0, None, 8080, 443])
    if rng.random() < 0.4:
        d["adapter"] = pick(["generic", "", None, "shelly"])
    if rng.random() < 0.5:
        d["name"] = pick(NAMES)
    if rng.random() < 0.4:
        d["scan_info"] = pick(INFOS)
    if rng.random() < 0.4:
        d["name_source"] = pick(SOURCES)
    return d


def run_case():
    shutil.rmtree(BASE, ignore_errors=True)
    BASE.mkdir(parents=True)
    devices_config.CONFIG_DIR = BASE / "cfg"
    devices_config.DEVICES_PATH = BASE / "cfg" / "devices.yaml"
    p = devices_config.DEVICES_PATH
    mode = rng.random()
    if mode < 0.15:
        pass
    else:
        p.parent.mkdir(parents=True)
        if mode < 0.2:
            p.write_text("", encoding="utf-8")
        elif mode < 0.23:
            p.write_text("devices:\n", encoding="utf-8")
        elif mode < 0.25:
            p.write_text("- a\n- b\n", encoding="utf-8")
        else:
            p.write_text(devices_config.yaml.safe_dump({"other": 1, "devices": [existing_entry() for _ in range(rng.randrange(0, 5))]}, sort_keys=False), encoding="utf-8")
    news = [new_device() for _ in range(rng.randrange(0, 9))]
    try:
        ret = devices_config.add_devices(news)
    except Exception as exc:
        ret = {"exception": type(exc).__name__}
    left = sorted(x.name for x in p.parent.glob("*")) if p.parent.exists() else None
    return [json.loads(json.dumps(ret, default=repr)), p.read_text(encoding="utf-8") if p.exists() else None, left]


cases = [run_case() for _ in range(N)]
digests = [hashlib.sha1(json.dumps(c).encode()).hexdigest()[:12] for c in cases]
out = json.loads(json.dumps({"digests": digests, "sample": cases[:25]}))
if os.environ.get("DEVICES_ADD_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(out, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want["digests"]) == len(digests) == N
for i, (x, y) in enumerate(zip(digests, want["digests"])):
    assert x == y, "case %d differs: %s" % (i, json.dumps(cases[i])[:700])
assert out["sample"] == want["sample"]
ex = [c for c in cases if isinstance(c[0], dict)]
assert 30 < len(ex) < 700, len(ex)
oks = [c[0] for c in cases if isinstance(c[0], list)]
assert sum(1 for r in oks if len(r) >= 3) > 200 and sum(1 for r in oks if not r) > 100, "scenarios too uniform"
flat = [e for r in oks for e in r]
assert any(e["id"].endswith("-3") for e in flat) and any(e["id"].endswith("-2") for e in flat), "no id suffixes"
assert any(e["port"] == 0 for e in flat) and any(e["port"] is None for e in flat) and any(e["adapter"] == "" for e in flat) and any(e["adapter"] is None for e in flat)
assert any("name" in e for e in flat) and any("name" not in e for e in flat) and any("scan_info" in e for e in flat) and any("scan_info" not in e for e in flat)
assert any("name_source" in e for e in flat) and any("name_source" not in e for e in flat)
assert any(c[1] is None for c in cases)
print("TUTTO OK")
