"""Golden-master test of scan_arp.parse_arp_scan (arp-scan output -> hosts, and the module's `arp_conflicts` dictionary: several MACs on one address, none of which also answers for
other addresses): 4000 generated outputs - repeated addresses (DUP lines), mixed-case MACs, vendors "(Unknown...)" or missing, header and junk lines, invalid addresses, a stale
`arp_conflicts` from a previous call - must give exactly the hosts (in order) AND the conflicts (in key order) stored in tests/golden/arp_scan.json, written from the code as it was
before the function was split.
Regenerate only on purpose:  ARPSCAN_GOLDEN_UPDATE=1 python tests/check_arp_scan_golden.py"""
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import scan_arp  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "arp_scan.json"
N = 4000
rng = random.Random(24680)
IPS = ["192.168.1.%d" % i for i in (1, 2, 3, 4, 5, 6)] + ["10.0.0.7"]
MACS = ["aa:bb:cc:00:00:0%d" % i for i in range(1, 7)] + ["AA:BB:CC:00:00:01", "Aa:bB:cC:00:00:02"]
VENDORS = ["Apple, Inc.", "(Unknown: locally administered)", "(Unknown)", " Espressif Inc. ", "", "TP-LINK"]
JUNK = ["Interface: eth0, type: EN10MB, MAC: aa:bb:cc:dd:ee:ff", "Starting arp-scan 1.10.0", "", "5 packets received by filter", "999.1.1.1\taa:bb:cc:00:00:01\tX", "192.168.1.9",
        "not an address\taa:bb:cc:00:00:01", "192.168.1.8\t"]


def pick(seq):
    return seq[rng.randrange(len(seq))]


def line():
    if rng.random() < 0.15:
        return pick(JUNK)
    parts = [pick(IPS), pick(MACS)]
    if rng.random() < 0.8:
        parts.append(pick(VENDORS))
    return "\t".join(parts)


out = []
for _ in range(N):
    text = "\n".join(line() for _ in range(rng.randrange(0, 14)))
    scan_arp.arp_conflicts.clear()
    if rng.random() < 0.3:
        scan_arp.arp_conflicts["172.16.0.1"] = ["stale"]
    try:
        hosts = scan_arp.parse_arp_scan(text)
        out.append({"hosts": hosts, "conflicts": list(scan_arp.arp_conflicts.items())})
    except Exception as exc:
        out.append({"exception": type(exc).__name__})
out = json.loads(json.dumps(out, sort_keys=True))
if os.environ.get("ARPSCAN_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(out, sort_keys=True, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want) == len(out) == N
for i, (x, y) in enumerate(zip(out, want)):
    assert x == y, "case %d differs: %s" % (i, json.dumps([x, y])[:500])
assert not any("exception" in o for o in out)
with_conflicts = sum(1 for o in out if o["conflicts"])
with_hosts = sum(1 for o in out if o["hosts"])
assert with_conflicts > 150 and with_hosts > 3000 and any(len(o["conflicts"]) > 1 for o in out), "scenarios too uniform (%d, %d)" % (with_conflicts, with_hosts)
assert any(h["vendor"] is None for o in out for h in o["hosts"]) and any(h["vendor"] for o in out for h in o["hosts"])
print("TUTTO OK")
