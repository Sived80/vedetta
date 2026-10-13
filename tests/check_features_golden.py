"""Golden-master test of maclayer.features_for_linking: 4500 generated inputs - observation rows of arp/dhcp/mdns sources, sessions (with or without mdns), DHCP entries with
mixed-case keys and partial fields, None or empty DHCP memory - must give exactly what is stored in tests/golden/features.json, written from the code as it was before the
function was split (key order included).
Regenerate only on purpose:  FEATURES_GOLDEN_UPDATE=1 python tests/check_features_golden.py"""
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import maclayer  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "features.json"
N = 4500
rng = random.Random(13579)
MACS = ["AA:BB:CC:00:00:0%d" % i for i in range(1, 6)]
IPS = ["192.168.1.%d" % i for i in range(1, 6)]
SOURCES = ["arp", "dhcp", "mdns"]
TIMES = [0.0, 0.5, -3.0, 10.0, 1000.0, 1.7e9, 5e17, 2e18, 123.25]


def pick(seq):
    return seq[rng.randrange(len(seq))]


def rows():
    out = []
    for _ in range(rng.randrange(0, 9)):
        a, b = pick(TIMES), pick(TIMES)
        out.append({"source": pick(SOURCES), "mac": pick(MACS), "ip": pick(IPS), "first_seen": a, "last_seen": b})
    return out


def sessions():
    out = []
    for _ in range(rng.randrange(0, 7)):
        out.append({"source": pick(SOURCES), "mac": pick(MACS + MACS + [m.lower() for m in MACS]), "ip": pick(IPS), "start": pick(TIMES), "end": pick(TIMES)})
    return out


def dhcp():
    r = rng.random()
    if r < 0.1:
        return None
    if r < 0.2:
        return {}
    out = {}
    for _ in range(rng.randrange(1, 5)):
        key = pick(MACS)
        if rng.random() < 0.5:
            key = key.lower()
        e = {}
        for f, vals in (("hostname", ["host", "", None]), ("client_id", ["01:aa", "", None]), ("vendor_class", ["MSFT 5.0", "", None]), ("prl", ["1,3,6", "", None, 0])):
            if rng.random() < 0.6:
                e[f] = pick(vals)
        out[key] = e if rng.random() < 0.95 else pick([None, {}])
    return out


def norm(v):
    if isinstance(v, set):
        return sorted(v)
    if isinstance(v, dict):
        return {k: norm(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [norm(x) for x in v]
    return v


out = []
for _ in range(N):
    args = (rows(), sessions(), dhcp())
    try:
        out.append(norm(maclayer.features_for_linking(*args)))
    except Exception as exc:
        out.append({"exception": type(exc).__name__})
out = json.loads(json.dumps(out))
if os.environ.get("FEATURES_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.parent.mkdir(exist_ok=True)
    GOLDEN.write_text(json.dumps(out, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want) == len(out) == N
for i, (x, y) in enumerate(zip(out, want)):
    assert x == y and json.dumps(x) == json.dumps(y), "case %d differs: %s" % (i, json.dumps([x, y])[:500])
assert not any(list(o) == ["exception"] for o in out), "unexpected exceptions"
vals = [f for o in out for f in o.values()]
for key in ("sessions", "hostname", "client_id", "fingerprint"):
    assert sum(1 for f in vals if key in f) > 500, key
assert any(f.get("fingerprint") == "|1,3,6" for f in vals) and any(f.get("fingerprint") == "MSFT 5.0|" for f in vals)
assert any(f["first"] == 1e18 for f in vals) and any(f["last"] == 0.0 for f in vals) and any(f["first"] < 0 for f in vals) and any(f["first"] == 5e17 for f in vals)
assert any(len(f["ips"]) > 1 for f in vals) and any("sessions" in f and len(f["sessions"]) > 1 for f in vals) and sum(1 for o in out if not o) > 20
print("TUTTO OK")
