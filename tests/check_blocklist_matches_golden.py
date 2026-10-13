"""Golden-master test of blocklist.matches (is a device in the ignore list, by MAC, IP, name or by the hostname announced via DHCP for its MAC): 4000 generated cases - empty list,
MAC in any case or with dashes, IP, names with spaces and capitals, empty entries, device name missing/empty, DHCP hostname known/unknown/empty/None, entries of every kind - must give
exactly the answers stored in tests/golden/blocklist_matches.json, written from the code as it was before the function was split.
`list_items` and `dhcp.seen` are replaced by in-memory data (the function has no other input).
Regenerate only on purpose:  BLOCKLIST_MATCHES_GOLDEN_UPDATE=1 python tests/a3_check_blocklist_matches_golden.py"""
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.storage import blocklist  # noqa: E402
from app.scan import dhcp  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "blocklist_matches.json"
N = 4000
rng = random.Random(1357913)
MACS = ["aa:bb:cc:00:00:01", "AA:BB:CC:00:00:02", "aa-bb-cc-00-00-03", "Aa:Bb:Cc:00:00:04", "aa:bb:cc:00:00:05"]
IPS = ["192.168.1.%d" % i for i in (1, 2, 3, 4)] + ["10.0.0.7"]
NAMES = ["Phone di Anna", "  phone   di anna ", "PHONE DI ANNA", "tv-salotto", "TV-Salotto", "printer", "Straße", "STRASSE", "x"]


def pick(seq):
    return seq[rng.randrange(len(seq))]


def maybe(seq, p=0.8):
    return pick(seq) if rng.random() < p else pick([None, "", " "])


def item(kind=None):
    kind = kind or pick(["mac", "ip", "name"])
    value = {"mac": MACS, "ip": IPS, "name": NAMES}[kind]
    v = pick(value) if rng.random() > 0.1 else pick(["", " "])
    if rng.random() < 0.2:
        v = " " + v + " "
    return {"id": "i%d" % rng.randrange(99), "kind": kind, "value": v}


out = []
by_scenario = {}
for _ in range(N):
    scenario = pick(["empty", "none", "mac", "ip", "name", "dhcp", "mixed"])
    items = [] if scenario == "empty" else [item() for _ in range(rng.randrange(1, 5))]
    mac, ip, name = maybe(MACS), maybe(IPS), maybe(NAMES)
    if scenario in ("mac", "ip", "name"):
        items.append(item(scenario))
    elif scenario == "dhcp":
        items.append(item("name"))
    rng.shuffle(items)
    dhcp.seen.clear()
    for m in MACS:
        if rng.random() < 0.5:
            dhcp.seen[m.lower()] = pick([{"hostname": pick(NAMES)}, {"hostname": ""}, {"hostname": None}, {}, None])
    blocklist.list_items = lambda items=items: items
    try:
        res = blocklist.matches(mac=mac, ip=ip, name=name)
        if rng.random() < 0.15:
            res = [res, blocklist.matches(mac=mac), blocklist.matches(ip=ip), blocklist.matches(name=name), blocklist.matches()]
    except Exception as exc:
        res = {"exception": type(exc).__name__}
    out.append(res)
    by_scenario.setdefault(scenario, []).append(res)
out = json.loads(json.dumps(out))
if os.environ.get("BLOCKLIST_MATCHES_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.parent.mkdir(exist_ok=True)
    GOLDEN.write_text(json.dumps(out), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want) == len(out) == N
for i, (x, y) in enumerate(zip(out, want)):
    assert x == y, "case %d differs: %s" % (i, json.dumps([x, y])[:500])
assert not any(isinstance(o, dict) for o in out)
simple = [o for o in out if isinstance(o, bool)]
assert sum(simple) > 600 and len(simple) - sum(simple) > 600, "too uniform"
for sc in ("mac", "ip", "name", "dhcp", "mixed"):
    assert sum(1 for r in by_scenario[sc] if r is True) > 60, "scenario %s rarely true" % sc
assert not any(r is True for r in by_scenario["empty"] if isinstance(r, bool))
assert any(isinstance(o, list) and o[0] is True and not o[1] for o in out)
assert any(isinstance(o, list) and o[0] is True and not o[2] for o in out)
assert any(isinstance(o, list) and o[0] is True and not o[3] for o in out)
print("TUTTO OK")
