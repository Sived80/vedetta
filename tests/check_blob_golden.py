"""Golden-master test of ha_data._blob (text, words and ports of a device): 4500 generated devices - generated and given names, brand/vendor of several types,
extra fields (ha_* ones, ha_model, non-text values), scanned ports with and without number - must give exactly what is stored in tests/golden/blob.json, written
from the code as it was before the function was split.
Regenerate only on purpose:  BLOB_GOLDEN_UPDATE=1 python tests/check_blob_golden.py"""
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import ha_data  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "blob.json"
N = 4500
rng = random.Random(97531)
NAMES = ["Living Room TV", "Apple phone", "", None, "MikroTik Router", "Camera da letto", "NAS-01", 0, 42, "x"]
BRANDS = ["Apple", "TP-Link", "", None, "Shelly", 7, 0]
VENDORS = ["Espressif Inc.", "", None, "Intel Corp", "Raspberry Pi Trading"]
EXTRA_KEYS = ["os", "model", "ha_model", "ha_area", "ha_integration", "title", "upnp_model", "hostname", "ha_", "HA_model", "ha_model_x", "hardware", "ha"]
EXTRA_VALS = ["Linux 4.14", "Windows 10", "lumi.camera.acn007", "Kitchen", "mikrotik_router", "C200 Camera", "", None, 5, ["a"], 3.5, "NAS Server"]
LABELS = ["80/tcp http", "  22 ssh", "8080", "http", "", None, "443/tcp HTTPS", "x 80", "9100 JetDirect", "0", "007 weird", "5900/tcp VNC"]


def pick(seq):
    return seq[rng.randrange(len(seq))]


def device():
    d = {}
    if rng.random() < 0.9:
        d["name"] = pick(NAMES)
    if rng.random() < 0.3:
        d["name_generated"] = pick([True, False, 1, 0, None])
    if rng.random() < 0.8:
        d["brand"] = pick(BRANDS)
    if rng.random() < 0.8:
        d["vendor"] = pick(VENDORS)
    r = rng.random()
    if r < 0.15:
        d["extra"] = pick([None, {}])
    elif r < 0.9:
        d["extra"] = {pick(EXTRA_KEYS): pick(EXTRA_VALS) for _ in range(rng.randrange(1, 6))}
    r = rng.random()
    if r < 0.15:
        d["scanned_ports"] = pick([None, []])
    elif r < 0.9:
        ports = []
        for _ in range(rng.randrange(1, 6)):
            p = {}
            if rng.random() < 0.9:
                p["label"] = pick(LABELS)
            ports.append(p)
        d["scanned_ports"] = ports
    return d


def norm(res):
    text, words, ports = res
    return [text, sorted(words), sorted(ports)]


out = []
for _ in range(N):
    d = device()
    try:
        out.append(norm(ha_data._blob(d)))
    except Exception as exc:
        out.append({"exception": type(exc).__name__})
out = json.loads(json.dumps(out))
if os.environ.get("BLOB_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.parent.mkdir(exist_ok=True)
    GOLDEN.write_text(json.dumps(out, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want) == len(out) == N
for i, (x, y) in enumerate(zip(out, want)):
    assert x == y, "case %d differs: %s" % (i, json.dumps([x, y])[:500])
ok = [o for o in out if not isinstance(o, dict)]
assert len(ok) > 3500, "too many exceptions"
assert sum(1 for o in ok if o[2]) > 1500 and sum(1 for o in ok if not o[0]) > 20 and sum(1 for o in ok if "apple" in o[0]) > 500
assert sum(1 for o in ok if "kitchen" in o[0]) < len(ok) // 2 and any("c200 camera" in o[0] for o in ok) and any("nas server" in o[0] for o in ok)
assert any("mikrotik_router" in o[0] for o in ok) and any(len(o[2]) > 2 for o in ok)
print("TUTTO OK")
