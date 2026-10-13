"""Golden-master test of IdentityUpkeep (identity_upkeep.py): _duplicate_key (the name that identifies a phone), follow_ip_changes (an offline device whose known MAC answers at exactly one
other address is followed there), merge_duplicate_phones (two cards of the same phone, grouped by name, merged when at least one is online and they were not online together for long)
and _merge_cards (the older card takes the address that answers, the other disappears). Generated worlds (cards, configuration, MACs, ARP view, history answers, failures of each
collaborator, equal timestamps and values right on the thresholds), with the collaborators replaced by deterministic in-memory ones (devices_config, history, a frozen clock, fake
alert/trigger/remove methods of a subclass): for each case the return value, the whole final state of the instance AND the ORDER and arguments of every call must be exactly the ones
stored in tests/golden/identity_upkeep.json (a digest per case, plus a readable sample), written from the code as it was before the functions were split.
Regenerate only on purpose:  IDENTITY_UPKEEP_GOLDEN_UPDATE=1 python tests/check_identity_upkeep_golden.py"""
import asyncio
import hashlib
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import identity_upkeep  # noqa: E402
from app.identity_upkeep import IdentityUpkeep  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "identity_upkeep.json"
N = 3200
rng = random.Random(97531)
LOG: list = []
CLOCK = [7_000_000.0]
LOOP = asyncio.new_event_loop()


def pick(seq):
    return seq[rng.randrange(len(seq))]


def ser(x):
    """Stable form of any value: dicts keep their key order, sets are sorted, exceptions are their type."""
    if isinstance(x, dict):
        return {"d": [[ser(k), ser(v)] for k, v in x.items()]}
    if isinstance(x, (list, tuple)):
        return [ser(v) for v in x]
    if isinstance(x, (set, frozenset)):
        return {"s": sorted((ser(v) for v in x), key=json.dumps)}
    if isinstance(x, BaseException):
        return {"exc": type(x).__name__}
    if x is None or isinstance(x, (str, int, float, bool)):
        return x
    return {"obj": type(x).__name__}


class FakeTime:
    @staticmethod
    def time():
        v = CLOCK[0]
        CLOCK[0] += 0.5
        LOG.append(["time", v])
        return v


WORLD: dict = {}


class FakeConfig:
    @staticmethod
    def load_devices():
        LOG.append(["load_devices"])
        return WORLD["configs"]

    @staticmethod
    def update_ip(device_id, ip):
        LOG.append(["update_ip", device_id, ip])
        if device_id in WORLD["update_ip_fails"]:
            return None
        for c in WORLD["configs"]:
            if c["id"] == device_id:
                old = c["ip"]
                c["ip"] = ip
                return WORLD.get("old_override", {}).get(device_id, old)
        return None

    @staticmethod
    def remove_device(device_id):
        LOG.append(["remove_device", device_id])
        return device_id not in WORLD["remove_fails"]

    @staticmethod
    def update_scan_info(device_id, info):
        LOG.append(["update_scan_info", device_id, ser(info)])


class FakeHistory:
    @staticmethod
    def first_presence(ids):
        LOG.append(["first_presence", list(ids)])
        return {i: WORLD["first"][i] for i in ids if i in WORLD["first"]}

    @staticmethod
    def online_overlap(a, b, start, end):
        LOG.append(["online_overlap", a, b, start, end])
        return WORLD["overlap"]

    @staticmethod
    def reassign_device(old, new):
        LOG.append(["reassign_device", old, new])


identity_upkeep.time = FakeTime
identity_upkeep.devices_config = FakeConfig
identity_upkeep.history = FakeHistory


class Upkeep(IdentityUpkeep):
    def __init__(self):
        self.devices = {}
        self._last_mac = {}
        self._misses = {}
        self._conflicts_reported = set()
        self.merged_total = 0
        self.merge_report = None

    def emit_alert(self, text, key, **kw):
        LOG.append(["alert", text, key, ser(kw)])

    def trigger(self, **kw):
        LOG.append(["trigger", ser(kw)])

    def remove(self, device_id):
        LOG.append(["remove", device_id])
        self.devices.pop(device_id, None)


def state_of(u):
    return {k: ser(v) for k, v in sorted(vars(u).items())}


def run(coro):
    return LOOP.run_until_complete(coro)


NAMES = ["Anna's iPhone", "Annas-iPhone", "anna_s_iphone", "Giulia", "giulia", "iPhone", "iphone", " iPhone ", "iPad", "Android", "android_ab12", "phone", "Tablet", "Galaxy", "Pixel", "pixel",
         "Samsung", "Apple", " apple ", "Philips", "Philips Hue", "Samsung TV", "abc", "ab-c", "a.b.c", "abcd", "ab cd", "Ab Cd!", "localhost", "unknown", "Davide", "Luca Phone", "192.168.1.5",
         "192.168.1.6", "", None, "   ", "12345", "Pixel 7", "Galaxy S21", "Marco", "Telefono", "Cellulare", "Smartphone", "Xiaomi", "xiaomi"]
GOOD_NAMES = ["Anna's iPhone", "Giulia", "Davide", "Luca Phone", "Pixel 7", "Marco", "abcd", "Galaxy S21", "Samsung TV", "Xiaomi"]
IPS = ["192.168.1.%d" % i for i in range(2, 12)]
MAC_POOL = ["aa:bb:cc:00:00:0%d" % i for i in range(1, 7)] + ["AA-BB-CC-00-00-02", " aa:bb:cc:00:00:03 ", "00:00:00:00:00:00", "01:00:5e:00:00:01", "zz", "", None]


def rand_device(i, ip=None):
    d = {"id": "d%d" % i, "name": pick(NAMES), "ip": ip or pick(IPS)}
    r = rng.random()
    if r < 0.45:
        d["online"] = True
    elif r < 0.85:
        d["online"] = False
    elif r < 0.92:
        d["online"] = None
    if rng.random() < 0.85:
        d["is_mobile"] = pick([True, True, True, False, None, 1, 0])
    return d


# ------------------------------------------------------------------ _duplicate_key
def case_key():
    d = {"name": pick(NAMES)}
    r = rng.random()
    if r < 0.2:
        d["name"] = " " + pick(IPS) + " "
        d["ip"] = d["name"].strip()
    elif r < 0.4:
        d["ip"] = pick(IPS)
    elif r < 0.55:
        d["ip"] = d["name"]
    elif r < 0.6:
        d = {}
    elif r < 0.65:
        d = {"name": None, "ip": None}
    try:
        res = IdentityUpkeep._duplicate_key(d)
    except Exception as exc:
        res = ser(exc)
    return {"dev": d, "res": res}


# ------------------------------------------------------------------ follow_ip_changes
def case_follow():
    n = rng.randrange(0, 6)
    configs = [{"id": "d%d" % i, "ip": pick(IPS + [""] if rng.random() < 0.1 else IPS)} for i in range(n)]
    if rng.random() < 0.15 and n >= 2:
        configs[1]["ip"] = configs[0]["ip"]
    u = Upkeep()
    macs = {}
    for c in configs:
        if rng.random() < 0.88:
            d = {"id": c["id"], "name": pick(NAMES + ["", None]), "online": pick([False, False, False, True, None])}
            u.devices[c["id"]] = d
        if rng.random() < 0.85:
            m = pick(MAC_POOL[:5] + MAC_POOL)
            macs[c["id"]] = m
            u._last_mac[c["id"]] = m
        u._misses[c["id"]] = pick([0, 1, 3])
    arp = {}
    for c in configs:
        m = macs.get(c["id"])
        if m is None:
            continue
        k = pick([0, 1, 1, 1, 2, 3])
        for ip in rng.sample(IPS, k):
            arp[ip] = {"mac": pick([m, m, m.upper() if isinstance(m, str) else m, "aa:bb:cc:00:00:09"])}
        if rng.random() < 0.1:
            arp[c["ip"]] = {"mac": m}
    for ip in rng.sample(IPS, rng.randrange(0, 4)):
        arp.setdefault(ip, {"mac": pick(MAC_POOL)} if rng.random() < 0.9 else {})
    if rng.random() < 0.05:
        arp = pick([{}, None])
    elif arp and rng.random() < 0.03:
        arp[pick(sorted(arp))] = None
    WORLD.clear()
    WORLD.update(configs=configs, update_ip_fails={c["id"] for c in configs if rng.random() < 0.15},
                 old_override={c["id"]: pick(IPS + [""]) for c in configs if rng.random() < 0.12})
    LOG.clear()
    try:
        res = ser(run(u.follow_ip_changes(arp)))
    except Exception as exc:
        res = ser(exc)
    return {"res": res, "state": state_of(u), "configs": ser(configs), "log": list(LOG)}


# ------------------------------------------------------------------ merge_duplicate_phones
def rand_scan_info():
    return pick([None, {}, {"scanned_at": 0}, {"scanned_at": 1}, {"scanned_at": 5}, {"scanned_at": 10}, {"other": 1}, {"scanned_at": 5, "ports": [80]}])


def case_merge_phones():
    u = Upkeep()
    n = rng.randrange(0, 7) if rng.random() < 0.1 else rng.randrange(2, 7)
    base = pick(GOOD_NAMES)
    same = rng.randrange(0, 5)   # how many cards get the same distinctive name
    for i in range(n):
        d = rand_device(i)
        if i < same:
            d["name"] = base
            d["is_mobile"] = pick([True, True, True, True, False, None])
        elif rng.random() < 0.2:
            d["name"] = base
        u.devices[d["id"]] = d
        if rng.random() < 0.5:
            u._last_mac[d["id"]] = pick(MAC_POOL)
    u.merged_total = pick([0, 0, 1, 3])
    now = CLOCK[0]
    configs = []
    for d in u.devices.values():
        if rng.random() < 0.93:
            c = {"id": d["id"], "ip": d["ip"]}
            si = rand_scan_info()
            if si is not None or rng.random() < 0.5:
                c["scan_info"] = si
            configs.append(c)
    WORLD.clear()
    WORLD.update(configs=configs, update_ip_fails={c["id"] for c in configs if rng.random() < 0.12},
                 remove_fails={c["id"] for c in configs if rng.random() < 0.12},
                 first={d: now + pick([-5000, -5000, -100, 0, 50]) for d in u.devices if rng.random() < 0.7},
                 overlap=pick([0, 1799, 1800, 1800.5, 1801, 99999]))
    LOG.clear()
    try:
        res = ser(run(u.merge_duplicate_phones()))
    except Exception as exc:
        res = ser(exc)
    return {"res": res, "state": state_of(u), "devices": ser(u.devices), "configs": ser(configs), "log": list(LOG)}


# ------------------------------------------------------------------ _merge_cards
def case_merge_cards():
    u = Upkeep()
    keep, drop = rand_device(0), rand_device(1)
    if rng.random() < 0.15:
        drop["ip"] = keep["ip"]
    for d in (keep, drop):
        if rng.random() < 0.9:
            u.devices[d["id"]] = d
        if rng.random() < 0.5:
            u._last_mac[d["id"]] = pick(MAC_POOL)
    configs = []
    for d in (keep, drop):
        if rng.random() < 0.92:
            c = {"id": d["id"], "ip": d["ip"]}
            si = rand_scan_info()
            if si is not None or rng.random() < 0.5:
                c["scan_info"] = si
            configs.append(c)
    WORLD.clear()
    WORLD.update(configs=configs, update_ip_fails={c["id"] for c in configs if rng.random() < 0.15},
                 remove_fails={c["id"] for c in configs if rng.random() < 0.15})
    now = float(rng.randrange(1, 100))
    LOG.clear()
    try:
        res = ser(run(u._merge_cards(keep=keep, drop=drop, now=now)))
    except Exception as exc:
        res = ser(exc)
    return {"res": res, "state": state_of(u), "devices": ser(u.devices), "configs": ser(configs), "log": list(LOG)}


CASES = [case_key, case_follow, case_merge_phones, case_merge_cards]
out = [CASES[i % 4]() for i in range(N)]
digests = [hashlib.sha1(json.dumps(o).encode()).hexdigest() for o in out]
doc = {"digests": digests, "sample": out[:20]}
if os.environ.get("IDENTITY_UPKEEP_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(doc, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want["digests"]) == len(digests) == N
for i, (x, y) in enumerate(zip(digests, want["digests"])):
    assert x == y, "case %d differs: %s" % (i, json.dumps(out[i])[:700])
assert json.loads(json.dumps(out[:20])) == want["sample"]

# the scenarios are varied enough
keys = [o for i, o in enumerate(out) if i % 4 == 0]
fol = [o for i, o in enumerate(out) if i % 4 == 1]
mph = [o for i, o in enumerate(out) if i % 4 == 2]
mcd = [o for i, o in enumerate(out) if i % 4 == 3]
assert sum(1 for o in keys if o["res"] is None) > 200 and sum(1 for o in keys if isinstance(o["res"], str)) > 100
assert sum(1 for o in fol if any(l[0] == "update_ip" for l in o["log"])) > 100
assert sum(1 for o in fol if any(l[0] == "trigger" for l in o["log"])) > 60
assert sum(1 for o in fol if o["log"] == [] or o["log"] == [["load_devices"]]) > 50
assert sum(1 for o in fol if any(l[0] == "update_ip" for l in o["log"]) and not any(l[0] == "alert" for l in o["log"])) > 5, "update_ip failures"
assert sum(1 for o in mph if any(l[0] == "alert" for l in o["log"])) > 40
assert sum(1 for o in mph if any(l[0] == "online_overlap" for l in o["log"]) and not any(l[0] == "remove_device" for l in o["log"])) > 20
assert sum(1 for o in mph if any(l[0] == "first_presence" for l in o["log"])) > 100
assert sum(1 for o in mph if any(l[0] == "update_scan_info" for l in o["log"])) >= 5
assert sum(1 for o in mph if o["state"]["merge_report"]["d"][0][1] == 0 and o["state"]["merge_report"]["d"][1][1] > 0) > 10
assert sum(1 for o in mph if o["state"]["merge_report"]["d"][2][1] > 0) > 10
assert sum(1 for o in mph if o["state"]["merge_report"]["d"][3][1] > 0) > 10
assert sum(1 for o in mcd if any(l[0] == "alert" for l in o["log"])) > 300
assert sum(1 for o in mcd if any(l[0] == "update_scan_info" for l in o["log"])) > 100
assert sum(1 for o in mcd if any(l[0] == "update_ip" for l in o["log"]) and any(l[0] == "update_ip" for l in o["log"]) and not any(l[0] == "reassign_device" for l in o["log"])) > 10
assert sum(1 for o in mcd if any(l[0] == "remove_device" for l in o["log"]) and not any(l[0] == "update_ip" for l in o["log"]) and any(l[0] == "alert" for l in o["log"])) > 100
assert sum(1 for o in mcd if o["log"] == [["load_devices"]]) > 10
print("TUTTO OK")
