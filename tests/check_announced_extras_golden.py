"""Golden-master test of probe._add_announced_name_extras (the names and models a device announces - Bonjour, NetBIOS, UPnP - copied into `extra` unless already there, the names
also only when they differ from the device name): 3000 generated cases - every key present, empty or equal to the device name, `extra` already holding some of the keys - must give
exactly the content AND the key order of `extra` stored in tests/golden/announced_extras.json, written from the code as it was before the function was rewritten as a table.
Regenerate only on purpose:  ANNOUNCED_GOLDEN_UPDATE=1 python tests/check_announced_extras_golden.py"""
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import probe  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "announced_extras.json"
N = 3000
rng = random.Random(70707)
VALUES = [None, "", "Salotto", "salotto", "living", "KB-123", "SM-S911B", "x"]
SCAN_KEYS = ["mdns_name", "netbios_name", "upnp_name", "upnp_model", "mdns_model"]
EXTRA_KEYS = ["mdns", "netbios", "upnp_name", "upnp_model", "mdns_model", "dhcp", "brand"]


def pick(seq):
    return seq[rng.randrange(len(seq))]


out = []
for _ in range(N):
    scan_info = {k: pick(VALUES) for k in SCAN_KEYS if rng.random() < 0.7}
    device = pick([{}, {"name": "Salotto"}, {"name": None}, {"name": "living"}])
    extra = {k: pick(["old", "", None]) for k in rng.sample(EXTRA_KEYS, rng.randrange(0, 4))}
    before = dict(extra)
    try:
        probe._add_announced_name_extras(extra, scan_info, device)
        out.append({"extra": list(extra.items()), "before": list(before.items())})
    except Exception as exc:
        out.append({"exception": type(exc).__name__})
out = json.loads(json.dumps(out, sort_keys=True))
if os.environ.get("ANNOUNCED_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(out, sort_keys=True, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want) == len(out) == N
for i, (x, y) in enumerate(zip(out, want)):
    assert x == y, "case %d differs: %s" % (i, json.dumps([x, y])[:500])
assert not any("exception" in o for o in out)
added = sum(1 for o in out if len(o["extra"]) > len(o["before"]))
assert added > 1500 and any(k == "netbios" for o in out for k, _ in o["extra"]) and any(k == "mdns_model" for o in out for k, _ in o["extra"]), "scenarios too uniform"
print("TUTTO OK")
