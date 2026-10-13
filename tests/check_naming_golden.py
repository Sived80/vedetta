"""Golden-master test of naming.clean_name and naming.title_name: 6000 generated strings (IPs, MACs, "id@name", domain suffixes, DNS-SD escapes, generated codes, page titles with
suffixes, versions, paths, generic words) must give exactly the results stored in tests/golden/naming.json, written from the code as it was before the two functions were split.
Regenerate only on purpose:  NAMING_GOLDEN_UPDATE=1 python tests/check_naming_golden.py"""
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.recognition import naming  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "naming.json"
N = 6000
rng = random.Random(31337)
WORDS = ["Salotto", "salotto", "pve", "Termostato", "iPhone-di-Anna", "Galaxy-S23", "Xiaomi-14", "ES", "AFTMM", "expiscor", "Android_MGDZ1OUL", "esp32", "localhost", "unknown", "default",
         "Login", "log in", "Welcome", "404 Not Found", "Index of /", "nginx", "Proxmox Virtual Environment", "Main Menu", "WebUI", "Status", "x", "", " ", "-", "*", "n/a", "NULL"]
SEPS = [" ", "-", "_", ".", " - ", " | ", " – ", ": ", "@", "\\032", "\\.", "/", "("]
CODES = ["05837F86AB12", "deadbeef", "0123456789ab", "a1b2c3d4e5", "14", "S23", "1.47.45", "v2.0", "192.168.1.5", "10-0-0-7", "ip-10-0-0-7", "AA:BB:CC:DD:EE:FF", "aabbccddeeff"]
SUFFIXES = [".local", ".lan", ".home", ".fritz.box", ".localdomain", ".internal", ".home.arpa", ".homenet", ".example.com", ""]
EXTRAS = ["_airplay._tcp", "_http._tcp.local", "x.arpa", "(192.168.1.5)", "[10.0.0.1]", "Name (192.168.1.9)", "v3", "Pro 2", "Hub", "a" * 41, "a" * 40]


def pick(seq):
    return seq[rng.randrange(len(seq))]


def make():
    parts = []
    for _ in range(rng.randrange(1, 4)):
        parts.append(pick([pick(WORDS), pick(CODES), pick(EXTRAS)]))
        if rng.random() < 0.7:
            parts.append(pick(SEPS))
    text = "".join(parts[:-1] if parts and parts[-1] in SEPS and rng.random() < 0.5 else parts) + pick(SUFFIXES)
    return pick([text, text, text.upper(), text.lower(), "  " + text + "  ", None, ""]) if rng.random() < 0.15 else text


out = []
for _ in range(N):
    s = make()
    row = {"in": s}
    for fn in (naming.clean_name, naming.title_name):
        try:
            row[fn.__name__] = fn(s)
        except Exception as exc:
            row[fn.__name__] = {"exception": type(exc).__name__}
    out.append(row)
out = json.loads(json.dumps(out, sort_keys=True))
if os.environ.get("NAMING_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(out, sort_keys=True, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want) == len(out) == N
for i, (x, y) in enumerate(zip(out, want)):
    assert x == y, "case %d differs: %s" % (i, json.dumps([x, y])[:500])
assert not any(isinstance(o[k], dict) for o in out for k in ("clean_name", "title_name"))
ok_clean = sum(1 for o in out if o["clean_name"])
ok_title = sum(1 for o in out if o["title_name"])
assert 1200 < ok_clean < 5000 and 300 < ok_title < 4000, "scenarios too uniform (%d, %d)" % (ok_clean, ok_title)
print("TUTTO OK")
