"""Golden-master test of newdevices.evaluate (compares the MACs seen on the network with the known ones, writes the changes into the known_macs table and returns
(new to alert, full list of the new); the first search of a network only takes the baseline): 3000 generated runs with the collaborators replaced by deterministic in-memory ones - a fake history that stores the rows and records every
write, fake vendor lookups, a recording wrapper around the block check - must give exactly the return value (or the exception), the final rows of the table AND the ORDER of every call
(row writes with their arguments, vendor lookups, brand lookups, block checks) stored in tests/golden/register_macs.json, written from the code as it was before the function was
split (digest per case plus a readable sample). Cases: MACs unknown, known, new, ignored, configured by address or by MAC, inside baseline blocks (valid and invalid), empty or
missing address, hostname and vendor, rows with fields that changed or did not change, the module's "present" filter None or a set.
Regenerate only on purpose:  REGISTER_MACS_GOLDEN_UPDATE=1 python tests/check_register_macs_golden.py"""
import copy
import hashlib
import json
import os
import random
import sys
import tempfile
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()      # never the real folder of the developer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.storage import newdevices  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "register_macs.json"
N = 3000
rng = random.Random(5150)
LOG: list = []
CASE: dict = {}
_real_in_blocks = newdevices._in_blocks


def pick(seq):
    return seq[rng.randrange(len(seq))]


class FakeHistory:
    def __init__(self, rows):
        self.rows = copy.deepcopy(rows)

    def known_all(self):
        LOG.append(["known_all"])
        return copy.deepcopy(self.rows)

    def meta_get(self, key):
        LOG.append(["meta_get", key])
        return None if CASE["fresh_network"] else "1"

    def meta_set(self, key, value):
        LOG.append(["meta_set", key, value])

    def known_set(self, mac, first_seen, ip, vendor, hostname, status):
        LOG.append(["known_set", mac, first_seen, ip, vendor, hostname, status])
        self.rows[mac] = {"mac": mac, "first_seen": first_seen, "ip": ip, "vendor": vendor, "hostname": hostname, "status": status}


def fake_lookup_vendor(mac):
    LOG.append(["lookup_vendor", mac])
    return ["", None, "OUI Corp", "OUI Corp", "", None, "OUI Corp", "", "OUI Corp", None][int(mac[-1])]


def fake_resolve_vendor_info(mac, vendor, names=()):
    LOG.append(["resolve", mac, vendor, list(names)])
    return {"vendor": vendor, "brand": None if mac.endswith("2") else "Brand" + mac[-2:], "vendor_role": "board" if mac.endswith("3") else None}


def logged_in_blocks(ip, blocks):
    r = _real_in_blocks(ip, blocks)
    LOG.append(["in_blocks", ip, list(blocks), r])
    return r


newdevices.lookup_vendor = fake_lookup_vendor
newdevices.resolve_vendor_info = fake_resolve_vendor_info
newdevices._in_blocks = logged_in_blocks

MACS = ["AA:BB:CC:00:00:%02X" % i for i in range(0x10, 0x1A)]
IPS = ["192.168.1.%d" % i for i in (2, 3, 4, 5)] + ["10.9.0.7", "172.16.5.5", "", None]
HOSTS = [None, "", "phone", "tv-room"]
VENDORS = [None, "", "Acme", "Espressif"]
BLOCKS = [(), ("10.9.0.0/16",), ("192.168.1.0/24", "10.9.0.0/16"), ("bogus",), ("192.168.1.0/24", "bogus"), ("172.16.0.0/12",)]
STATUS = ["new", "new", "known", "ignored"]


def observed_entry():
    o = {"ip": pick(IPS), "hostname": pick(HOSTS), "vendor": pick(VENDORS)}
    if rng.random() < 0.01:
        del o[pick(["ip", "hostname", "vendor"])]
    return o


def row_for(mac):
    return {"mac": mac, "first_seen": float(rng.randrange(100, 900)), "ip": pick(IPS), "vendor": pick(VENDORS), "hostname": pick(HOSTS), "status": pick(STATUS)}


def ser(x):
    return json.loads(json.dumps(x, default=repr))


def run_case():
    LOG.clear()
    macs = rng.sample(MACS, rng.randrange(0, 7))
    observed = {m: observed_entry() for m in macs}
    rows = {m: row_for(m) for m in macs if rng.random() < 0.55}
    for m in MACS:
        if m not in macs and rng.random() < 0.2:
            rows[m] = row_for(m)
    for m, r in list(rows.items()):
        if m in observed and rng.random() < 0.4:                    # the same data as observed: no write expected
            o = observed[m]
            r.update(ip=o.get("ip"), hostname=o.get("hostname"), vendor=o.get("vendor") or r["vendor"])
    for m in list(rows):
        if rng.random() < 0.02:
            rows[m] = {}                                          # an empty row: not None, but with no data
    cips = {pick(IPS) for _ in range(rng.randrange(0, 3))}
    cmacs = {pick(MACS) for _ in range(rng.randrange(0, 3))}
    hist = FakeHistory(rows)
    CASE["fresh_network"] = rng.random() < 0.1                    # the baseline of the network is not taken yet
    ignore = {pick(MACS) for _ in range(rng.randrange(1, 3))} if rng.random() < 0.15 else set()
    now = float(rng.randrange(1000, 2000))
    blocks = pick(BLOCKS)
    try:
        ret = newdevices.evaluate(observed, cips, cmacs, ignore, hist, now, blocks)
        res = {"ret": ser(ret)}
    except Exception as exc:
        res = {"exception": type(exc).__name__}
    res["table"] = ser(hist.rows)
    res["log"] = ser(LOG)
    return res


cases = [run_case() for _ in range(N)]
digests = [hashlib.sha1(json.dumps(c).encode()).hexdigest()[:12] for c in cases]
out = json.loads(json.dumps({"digests": digests, "sample": cases[:12]}))
if os.environ.get("REGISTER_MACS_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(out, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want["digests"]) == len(digests) == N
for i, (x, y) in enumerate(zip(digests, want["digests"])):
    assert x == y, "case %d differs: %s" % (i, json.dumps(cases[i])[:900])
assert out["sample"] == want["sample"]
ex = [c for c in cases if "exception" in c]
assert 5 < len(ex) < 300, len(ex)
good = [c for c in cases if "ret" in c]
assert sum(1 for c in good if c["ret"][0]) > 800 and sum(1 for c in good if c["ret"][1]) > 800, "scenarios too uniform"
logs = [[e[0] for e in c["log"]] for c in good]
assert sum(1 for L in logs if "known_set" in L) > 1500 and sum(1 for L in logs if "lookup_vendor" in L) > 1500 and sum(1 for L in logs if "in_blocks" in L) > 1000
assert sum(1 for c in good if any(e[0] == "in_blocks" and e[3] for e in c["log"])) > 100 and sum(1 for c in good if any(e[0] == "in_blocks" and not e[3] for e in c["log"])) > 400
assert sum(1 for c in good if any(e[0] == "known_set" and e[6] == "known" for e in c["log"])) > 500
assert sum(1 for c in good if any(e[0] == "known_set" and e[6] == "new" for e in c["log"])) > 500 and sum(1 for c in good if any(e[0] == "known_set" and e[6] == "ignored" for e in c["log"])) > 50
assert sum(1 for c in good if any(e[0] == "known_set" and isinstance(e[2], float) and e[2] < 1000 for e in c["log"])) > 400, "no update of an existing row"
assert sum(1 for c in good if not any(e[0] == "known_set" for e in c["log"]) and c["ret"][0] == []) > 100, "no case without writes"
assert sum(1 for c in good if any(e[0] == "meta_set" for e in c["log"])) > 100, "no baseline taken"
print("TUTTO OK")
