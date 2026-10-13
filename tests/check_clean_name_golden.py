"""Golden-master test of naming.clean_name: 1500 generated raw names (seeded, always the same) built from the awkward pieces - addresses inside the name,
"<id>@<name>", domain suffixes, DNS-SD escapes and service types, generated hex codes, fully qualified names, generic words, IPs and MACs written as names,
empty and odd values - must give exactly the output stored in tests/golden/clean_name.json, written from the code as it was before the function was split.
Regenerate only on purpose:  NAME_GOLDEN_UPDATE=1 python tests/check_clean_name_golden.py"""
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.recognition import naming  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "clean_name.json"
N = 1500
rng = random.Random(2468)
PIECES = [
    "Salotto", "Xiaomi-14", "Galaxy S23", "tv", "ES", "AFTMM", "expiscor", "amzn.dmgr.05837F86A1B2", "05837F86", "deadbeef01", "iPhone di Anna", "nas",
    "192.168.1.5", "(192.168.1.5)", "[10.0.0.7]", "ip-10-0-0-7", "10-0-0-7", "f0:18:98:aa:bb:cc", "F0-18-98-AA-BB-CC", "f01898aabbcc",
    "localhost", "unknown", "Device", "n/a", "-", "*", "none", "(null)", "_airplay", "x._tcp", "y._udp", "1.0.0.127.in-addr.arpa", "\\032", "\\.", "\\065",
    ".local", ".lan", ".home", ".fritz.box", ".localdomain", ".internal", ".home.arpa", ".homenet", "host.example.com", "a.b", "@", " ", "_", "--", ",", ":",
]
JOIN = ["", "", " ", "@", ".", "-", "_", "(", ")"]
out = []
for i in range(N):
    if i % 97 == 0:
        raw = rng.choice([None, "", 0, "   ", 5, "\t"])
    else:
        raw = "".join(rng.choice(PIECES) + rng.choice(JOIN) for _ in range(rng.randrange(1, 5)))
    try:
        out.append([raw if isinstance(raw, (str, type(None))) else str(raw), naming.clean_name(raw)])
    except Exception as exc:
        out.append([str(raw), {"exception": type(exc).__name__}])
out = json.loads(json.dumps(out))
if os.environ.get("NAME_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(out, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want) == len(out) == N
for i, (x, y) in enumerate(zip(out, want)):
    assert x == y, "case %d differs: %s" % (i, json.dumps([x, y])[:500])
res = [r for _, r in out]
assert sum(1 for r in res if r is None) > 200 and sum(1 for r in res if isinstance(r, str)) > 200, "scenarios too uniform"
assert not any(isinstance(r, dict) for r in res)
print("TUTTO OK")
