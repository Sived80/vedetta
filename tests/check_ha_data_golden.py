"""Golden-master test of ha_data._assemble_summary (counts, brand list, unknown chips, types in order, poll, activity): 3000 generated inputs must give exactly the values stored in
tests/golden/ha_data.json, with the ORDER of the keys (the result is compared as text), written from the code as it was before the function was split.
(The clues of the device type, which this test also covered, are tested from end to end by tests/check_type_evidence_full_golden.py.)
Regenerate only on purpose:  HADATA_GOLDEN_UPDATE=1 python tests/check_ha_data_golden.py"""
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import ha_data  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "ha_data.json"
N_SUM = 3000
rng = random.Random(424242)


def pick(seq):
    return seq[rng.randrange(len(seq))]


def subset(seq, p):
    return [x for x in seq if rng.random() < p]


# ------------------------------------------------------------------ _assemble_summary
BRANDS = [None, "Acme", "acme", "Zeta", "Beta", "apple", "Apple", "", "Ünder"]
VENDORS = ["Espressif", "espressif", "Chip A", "chip b", "Zed", "AAA"]
TYPES = ["router", "pc", "phone", "media", "iot", "printer", "generic", "server", "audio", "weird", "other"]


def dev():
    d = {}
    for k, v in (("online", [True, False, None]), ("battery", ["yes", "no", None]), ("latency_ms", [None, 0, 10, 25.5, 100])):
        if rng.random() < 0.85:
            d[k] = pick(v)
    return d


def sum_case():
    devices = [dev() for _ in range(pick([0, 0, 1, 2, 3, 5, 8]))]
    mobile = devices[: rng.randrange(0, len(devices) + 1)]
    online = sum(1 for d in devices if d.get("online"))
    types = {t: rng.randrange(1, 5) for t in subset(TYPES, 0.4)}
    brands = {b: rng.randrange(1, 4) for b in subset(BRANDS, 0.4)}
    chips = {v: rng.randrange(1, 4) for v in subset(VENDORS, 0.4)}
    poll = pick([{}, {"interval_ms": 1000, "next_in_ms": 5, "paused": True, "paused_in_ms": 2, "paused_total_ms": 9}, {"paused": 0}, {"interval_ms": 5, "paused": 1}, {"next_in_ms": 0, "paused": ""}])
    new_devices = pick([{}, {"count": 2, "devices": ["a", "b"]}, {"count": 0}, {"devices": [1]}])
    activity = pick([{}, {"search": 1, "rescanning": ["a", "b"]}, {"search": 0, "rescanning": None}, {"rescanning": []}, {"search": True, "rescanning": ("x",)}])
    rev = pick([0, 3, 99])
    return devices, rev, online, mobile, types, poll, new_devices, brands, activity, chips


sums = []
sum_stats = {"zero": 0, "pct": 0, "tie": 0, "none_brand": 0, "types_order": 0, "paused": 0}
for _ in range(N_SUM):
    a = sum_case()
    try:
        r = ha_data._assemble_summary(a[0], a[1], ha_data._Tally(a[2], a[3], a[7], a[9], a[4]), a[5], a[6], a[8])      # (the order of the generated values: devices, rev, online, mobile, types, poll, new devices, brands, activity, chips)
    except Exception as exc:
        r = {"exception": type(exc).__name__}
    sums.append([a[0], a[1], a[2], len(a[3]), [d for d in a[3]], a[4], a[5], a[6], a[7], a[8], a[9], json.dumps(r)])        # as text: the ORDER of the keys counts
    if "total" in r:
        sum_stats["zero"] += r["total"] == 0
        sum_stats["pct"] += r["online_pct"] is not None
        sum_stats["tie"] += len({b["count"] for b in r["brands"]}) < len(r["brands"])
        sum_stats["none_brand"] += any(b["brand"] is None for b in r["brands"])
        sum_stats["types_order"] += len(r["types"]) > 2
        sum_stats["paused"] += r["poll"]["paused"]

out = json.loads(json.dumps({"sum": sums}))
if os.environ.get("HADATA_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(out, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
for key, n in (("sum", N_SUM),):
    assert len(want[key]) == len(out[key]) == n
    for i, (x, y) in enumerate(zip(out[key], want[key])):
        assert x == y, "%s case %d differs: %s" % (key, i, json.dumps([x, y])[:900])
assert all(v > 100 for v in sum_stats.values()), sum_stats
assert sum(1 for o in out["sum"] if '"exception"' in o[11]) == 0
print("TUTTO OK")
