"""Golden-master test of mdns_listener.record (remembers an mDNS announcement per MAC, or per IP while the MAC is unknown): 4000 generated cases of one to three announcements each - valid and
invalid addresses, user-named and generic services, names from the TXT keys (friendly_name, fn, location_name, also empty and "slug" values), model / manufacturer keys, long names,
cards already stored under the MAC or the IP with every kind of score, services list and fields, `now` given or taken from the clock. `_mac_for_ip` and the clock are replaced by in-memory
fakes that record every call (so the number and order of the calls count too); the two memories, the dirty flag and the calls must match tests/golden/mdns_record.json, written from the
code as it was before the function was split (the key order of the cards counts).
Regenerate only on purpose:  MDNSRECORD_GOLDEN_UPDATE=1 python tests/check_mdns_record_golden.py"""
import copy
import json
import os
import random
import sys
import types
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import mdns_listener as ml  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "mdns_record.json"
N = 4000
rng = random.Random(5566778)


def pick(seq):
    return seq[rng.randrange(len(seq))]


IPS = ["192.168.1.10", "192.168.1.11", "192.168.1.12", "10.0.0.5"]
BAD_IPS = ["", "bad", "1.2.3", "::1", None, "256.1.1.1"]
MACS = [None, None, "", "aa:bb:cc:00:00:01", "aa:bb:cc:00:00:02", "aa:bb:cc:00:00:03"]
STYPES = ["_airplay._tcp", "_hap._tcp", "_http._tcp", "_googlecast._tcp", "_sonos._tcp", "_ssh._tcp", "", "_companion-link._tcp"]
INSTANCES = ["Salotto", "iPhone di Anna", "x" * 50, "", "5c53de3b-esphome", " Camera ", "Cucina"]
TXTS = ['"friendly_name=Salotto TV" "model=Chromecast"', '"fn=Fire TV" "am=AppleTV6,2"', '"location_name=Studio" "md=Home" "mf=Acme"', '"friendly_name=5c53de3b-esphome" "model=M"',
        '"friendly_name=" "fn=Bagno"', "", '"manufacturer=Sonos" "model=Era"', 'friendly_name=Raw Name', '"model=" "manufacturer="', '"friendly_name=%s"' % ("L" * 60), '"am=A1" "md=B2" "model=C3"',
        '"location_name=Loc" "fn=Fn" "friendly_name=Fri"', '"mf=Vendor" "model=%s"' % ("m" * 70), '"friendly_name=a-b" "fn=0abcdef0-zz"', '"fn=ab12cd34ef-x" "location_name=Loc2"']
SCORES = [0, 1, 2, 3, 4, "2", "3", None, "", 2.0, 0, 1, 2, "abc"]


def card():
    c = {}
    for k, pool in (("name", ["Old", "", None, "Vecchio nome"]), ("score", SCORES), ("model", ["OM", None, ""]), ("manufacturer", ["OMf", None]),
                    ("services", [["_http._tcp"], ["_airplay._tcp", "_ssh._tcp"], [], None]), ("ip", IPS), ("seen", [1.0, 5, 9999.5])):
        if rng.random() < 0.7:
            c[k] = pick(pool)
    keys = list(c)
    rng.shuffle(keys)
    return {k: c[k] for k in keys}


calls = []
clock = [5000.0]


def fake_time():
    clock[0] += 1.25
    calls.append(["time"])
    return clock[0]


ml.time = types.SimpleNamespace(time=fake_time)
out = []
stats = {"invalid": 0, "mac": 0, "ip": 0, "replaced_ip": 0, "now": 0, "dirty": 0, "name_kept": 0, "model": 0, "manufacturer": 0, "long": 0}
for _ in range(N):
    ml.by_mac.clear()
    ml.by_ip.clear()
    ml._dirty = False
    for m in MACS[3:]:
        if rng.random() < 0.5:
            ml.by_mac[m] = card()
    for ip in IPS:
        if rng.random() < 0.5:
            ml.by_ip[ip] = card()
    macs = {ip: pick(MACS) for ip in IPS + BAD_IPS if ip is not None}
    del calls[:]
    ml._mac_for_ip = lambda ip, macs=macs: (calls.append(["mac_for_ip", ip]), macs.get(ip))[1]
    before_ip = copy.deepcopy(ml.by_ip)
    res = []
    for _ in range(rng.randrange(1, 4)):
        ip = pick(IPS) if rng.random() < 0.9 else pick(BAD_IPS)
        stype, instance, txt = pick(STYPES), pick(INSTANCES), pick(TXTS)
        now = pick([None, None, 123.5, 0, 77]) if rng.random() < 0.6 else None
        try:
            ret = ml.record(ip, stype, instance, txt, now) if now is not None or rng.random() < 0.5 else ml.record(ip, stype, instance, txt)
            res.append({"ret": ret})
        except Exception as exc:
            res.append({"exception": type(exc).__name__})
        stats["invalid"] += ip in BAD_IPS
        stats["now"] += now is not None
    out.append({"res": res, "by_mac": list(ml.by_mac.items()), "by_ip": list(ml.by_ip.items()), "dirty": ml._dirty, "calls": copy.deepcopy(calls)})
    stats["dirty"] += ml._dirty
    stats["mac"] += any(c[0] == "mac_for_ip" and macs.get(c[1]) for c in calls)
    stats["ip"] += bool(ml.by_ip)
    stats["replaced_ip"] += len(ml.by_ip) < len(before_ip)
    stats["model"] += any(c.get("model") for c in list(ml.by_mac.values()) + list(ml.by_ip.values()))
    stats["manufacturer"] += any(c.get("manufacturer") for c in list(ml.by_mac.values()) + list(ml.by_ip.values()))
    stats["long"] += any(len(str(c.get("name"))) == 40 and str(c.get("name")).endswith("…") for c in list(ml.by_mac.values()) + list(ml.by_ip.values()))

text_out = json.dumps(out)  # no sort_keys: the key order counts
if os.environ.get("MDNSRECORD_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.parent.mkdir(exist_ok=True)
    GOLDEN.write_text(text_out, encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want) == len(out) == N
for i, (x, y) in enumerate(zip(out, want)):
    assert json.dumps(x) == json.dumps(y), "case %d differs: %s" % (i, json.dumps([x, y])[:700])
assert text_out == GOLDEN.read_text(encoding="utf-8"), "key order or formatting differs"
assert all(stats[k] > 300 for k in ("invalid", "mac", "ip", "replaced_ip", "now", "dirty", "model", "manufacturer", "long")), "too uniform: %s" % stats
n_exc = sum(1 for o in out for r in o["res"] if "exception" in r)
assert 0 < n_exc < 400, n_exc
print("TUTTO OK")
