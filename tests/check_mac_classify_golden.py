"""Golden-master test of macclassify.classify (what kind of MAC is each one, and which addresses are contested): 1500 generated situations - virtual and
locally administered MACs, a MAC lending several addresses with DHCP clients behind it, MACs seen only by DHCP or mDNS, an invalid MAC, with and without ARP
sessions, with and without flips, and contests built right at every threshold (3 sightings, 60 s of overlap, 6 flips, a median gap of 900 s, a flip gap of 600 s) -
must give exactly the output stored in tests/golden/mac_classify.json, written from the code as it was before the functions were split.
Regenerate only on purpose:  MACCLASS_GOLDEN_UPDATE=1 python tests/check_mac_classify_golden.py"""
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import macclassify  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "mac_classify.json"
N = 1500
rng = random.Random(20261010)
MACS = ["00:00:5E:00:01:0A", "00:00:0C:07:AC:01", "02:11:22:33:44:01", "DA:11:22:33:44:02", "f0:18:98:aa:bb:01", "3c:22:fb:11:22:02", "b8:27:eb:00:00:03",
        "AA:bb:CC:dd:ee:04", "ZZ:11:22:33:44:05", "c8:0e:14:00:00:06", "00:00:0C:9F:F0:07"]
IPS = ["192.168.1.%d" % n for n in range(10, 17)]
BASE = 1_700_000_000


def pick(seq):
    return seq[rng.randrange(len(seq))]


def row(ip, mac, source, first, dur, count):
    return {"ip": ip, "mac": mac, "source": source, "first_seen": first, "last_seen": first + dur, "seen_count": count}


def case():
    macs = rng.sample(MACS, rng.randrange(1, 6))
    ips = rng.sample(IPS, rng.randrange(1, 6))
    rows, sessions = [], []
    for m in macs:
        k = 3 if rng.random() < 0.12 and len(ips) >= 3 else rng.randrange(1, 4)           # a lender answers at 3 addresses
        for ip in rng.sample(ips, min(k, len(ips))):
            first = BASE + rng.randrange(0, 5000)
            for source in [s for s, p in (("arp", 0.85), ("dhcp", 0.3), ("mdns", 0.15)) if rng.random() < p] or ["arp"]:
                rows.append(row(ip, m, source, first + rng.randrange(0, 200), pick([0, 30, 59, 60, 61, 300, 2000, 9000]), pick([1, 2, 3, 3, 4, 10])))
    sess_mode = pick([None, None, [], "gen", "gen", "gen", "gen"])
    if sess_mode == "gen":
        for r in rows:
            for _ in range(rng.randrange(0, 3)):
                if r["source"] == "arp":
                    s = r["first_seen"] + rng.randrange(0, 100)
                    sessions.append({"source": "arp", "mac": r["mac"], "ip": r["ip"], "start": s, "end": s + pick([0, 30, 59, 60, 61, 300, 2000])})
                elif r["source"] == "dhcp":
                    s = r["first_seen"] + rng.randrange(0, 700)
                    sessions.append({"source": "dhcp", "mac": r["mac"], "ip": r["ip"], "start": s, "end": s})
                elif rng.random() < 0.3:
                    sessions.append({"source": "mdns", "mac": r["mac"], "ip": r["ip"], "start": r["first_seen"], "end": r["last_seen"]})
        sessions_arg = sessions
    else:
        sessions_arg = sess_mode
    flips_arg = pick([None, None, [], "gen", "gen", "gen"])
    if flips_arg == "gen":
        flips_arg = []
        by_ip = {}
        for r in rows:
            if r["source"] == "arp":
                by_ip.setdefault(r["ip"], set()).add(r["mac"])
        for ip, ms in by_ip.items():
            ms = sorted(ms)
            if len(ms) >= 2 and rng.random() < 0.8:
                a, b = ms[0], ms[1]
                if rng.random() < 0.6 and sessions_arg:                       # a contest right at the thresholds: overlapping sessions, many flips
                    t0 = BASE + 100
                    ov = pick([0, 30, 59, 60, 61, 300])
                    sessions_arg.append({"source": "arp", "mac": a, "ip": ip, "start": t0, "end": t0 + 500})
                    sessions_arg.append({"source": "arp", "mac": b, "ip": ip, "start": t0 + 500 - ov, "end": t0 + 1500})
                k = pick([3, 5, 6, 7, 8, 10])
                steps = [pick([100, 600, 899, 900, 901, 1500]) for _ in range(k)] if rng.random() < 0.5 else [pick([100, 600, 899, 900, 901, 1500])] * k     # an even or an uneven rhythm: the median is told apart
                designed = rng.random() < 0.2
                if designed:                                       # six gaps, three short and three just over the limit: the upper and the lower median fall on different sides of it
                    k = 7
                    head = [100, 100, 100, 901, 901, 901]
                    rng.shuffle(head)
                    steps = head + [100]
                ts = BASE + 200
                for j in range(k):
                    f = {"ip": ip, "old": a if j % 2 == 0 else b, "new": b if j % 2 == 0 else a, "ts": ts}
                    ts += steps[j]
                    gap = 0 if designed else pick([0, 100, 600, 601, 650, None])
                    if gap is not None:
                        f["gap"] = gap
                    flips_arg.append(f)
    return rows, sessions_arg, flips_arg


out = []
for _ in range(N):
    rows, sessions, flips = case()
    try:
        out.append(macclassify.classify(rows, sessions, flips))
    except Exception as exc:
        out.append({"exception": type(exc).__name__})
out = json.loads(json.dumps(out, sort_keys=True, default=str))
if os.environ.get("MACCLASS_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(out, sort_keys=True, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want) == len(out) == N
for i, (x, y) in enumerate(zip(out, want)):
    assert x == y, "case %d differs: %s" % (i, json.dumps([x, y])[:600])
assert not any("exception" in o for o in out), [o for o in out if "exception" in o][:2]
kinds = {m["kind"] for o in out for m in o["macs"].values()}
assert {"virtual", "lender", "multi_address", "private", "normal", "conflict"} <= kinds, kinds
counts = (sum(1 for o in out if o["conflicts"]), sum(1 for o in out if o["possible_conflicts"]), sum(1 for o in out if o["clients"]))
assert counts[0] > 12 and counts[1] > 4 and counts[2] > 200, "scenarios too uniform (cases with a conflict, with a possible one, with clients): %s" % (counts,)
assert sum(1 for o in out for m in o["macs"].values() if m["behind"]) > 20
print("TUTTO OK")
