"""Golden-master test of four helpers of recognition/roles.py: _find_clients_behind_repeaters (same MAC on several addresses -> the clients behind a repeater, plus the
repeater role added through the add_ callback), _build_roles_result (roles in the fixed order, UPnP types, what the DHCP servers hand out), _record_dhcp_offers (remembers the
offers, journal lines, log line, alert for several servers) and _store_roles_and_notify (stores the result, log and journal only when something changed, change callback).
Generated inputs, with the collaborators replaced by deterministic in-memory ones (frozen clock, fake logger, fake journal, fake callbacks): for each case the return value, the
side effects on the arguments AND on the module state, and the ORDER of every call (add_, log, journal, alert, change event, clock) must be exactly the ones stored in
tests/golden/roles_helpers.json (a digest per case, plus a readable sample), written from the code as it was before the functions were split.
Regenerate only on purpose:  ROLES_HELPERS_GOLDEN_UPDATE=1 python tests/check_roles_helpers_golden.py"""
import hashlib
import json
import os
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.recognition import roles  # noqa: E402
from app.storage import journal  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "roles_helpers.json"
N = 3000
rng = random.Random(4242)
LOG: list = []
CLOCK = [5_000_000.0]


def pick(seq):
    return seq[rng.randrange(len(seq))]


def ser(x):
    """Stable form of any value: dicts keep their key order, sets are sorted, exceptions are their type and text."""
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
    return {"obj": repr(x)}


class FakeTime:
    @staticmethod
    def time():
        v = CLOCK[0]
        CLOCK[0] += 0.5
        LOG.append(["time", v])
        return v


class FakeLogger:
    def __getattr__(self, name):
        def call(fmt, *args, **kw):
            LOG.append(["log", name, fmt, ser(list(args)), ser(kw)])
        return call


def fake_journal_add(kind, key, **kw):
    LOG.append(["journal", kind, key, ser(kw)])


def fake_on_alert(text, key, **kw):
    LOG.append(["alert", text, key, ser(kw)])


def fake_on_change(ev):
    LOG.append(["change", ser(ev)])


roles.time = FakeTime
roles.logger = FakeLogger()
journal.add = fake_journal_add

IPS = ["192.168.1.%d" % i for i in range(1, 9)] + ["10.0.0.2"]
MACS = ["aa:bb:cc:00:00:0%d" % i for i in range(1, 6)] + ["AA-BB-CC-00-00-01", " aa:bb:cc:00:00:02 ", "00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff",
                                                         "01:00:5e:00:00:01", "zz", "", None]
ROLE_NAMES = ["gateway", "dhcp", "dns", "router", "ap", "repeater", "mystery"]
SOURCES = ["route", "offer", "dhcp", "dns", "upnp", "arp", ""]
LABELS = ["Router", "Ext 1", "", None, "Mesh"]


def rand_by_ip(ips):
    out = {}
    for ip in ips:
        if rng.random() < 0.6:
            roles_d = {}
            for r in rng.sample(ROLE_NAMES, rng.randrange(0, 5)):
                roles_d[r] = pick(SOURCES)
            out[ip] = roles_d
    return out


def run_find(case_rng_unused=None):
    ips = rng.sample(IPS, rng.randrange(0, 8))
    arp = {}
    for ip in ips:
        r = rng.random()
        if r < 0.03:
            arp[ip] = None if rng.random() < 0.5 else {}
        else:
            host = {"mac": pick(MACS)} if rng.random() < 0.95 else {"vendor": "x"}
            arp[ip] = host
    # force shared macs often
    if rng.random() < 0.6 and len(arp) >= 2:
        m = pick(MACS[:5])
        for ip in rng.sample(sorted(arp), rng.randrange(2, len(arp) + 1)):
            arp[ip] = {"mac": m}
    by_ip = rand_by_ip(IPS)
    names = {ip: pick(LABELS) for ip in IPS if rng.random() < 0.5}
    if rng.random() < 0.3:
        names[None] = "nobody"
    ip_arg = pick(IPS + [None])
    LOG.clear()

    def add_(ip, role, source):
        LOG.append(["add", ip, role, source])
        if ip:
            by_ip.setdefault(ip, {}).setdefault(role, source)
    before = ser(by_ip)
    try:
        via = roles._find_clients_behind_repeaters(arp, ip_arg, add_, by_ip, names)
        res = ser(via)
    except Exception as exc:
        res = ser(exc)
    return {"res": res, "by_ip": ser(by_ip), "before": before, "log": list(LOG)}


def rand_offer():
    o = {}
    if rng.random() < 0.95:
        o["server"] = pick(IPS)
    for k in ("router", "dns"):
        r = rng.random()
        if r < 0.5:
            o[k] = rng.sample(IPS, rng.randrange(1, 3))
        elif r < 0.65:
            o[k] = []
        elif r < 0.75:
            o[k] = None
    for k, vals in (("domain", ["lan", "", None, "home.arpa"]), ("lease", [3600, 0, None, 86400]), ("netmask", ["255.255.255.0", "", None])):
        if rng.random() < 0.5:
            o[k] = pick(vals)
    if rng.random() < 0.2:
        o["extra"] = "zzz"
    return o


def run_build():
    ips = rng.sample(IPS, rng.randrange(0, 6))
    by_ip = {ip: {r: pick(SOURCES) for r in rng.sample(ROLE_NAMES, rng.randrange(0, 6))} for ip in ips}
    upnp = {}
    for ip in rng.sample(IPS, rng.randrange(0, 5)):
        info = {}
        r = rng.random()
        if r < 0.5:
            info["types"] = rng.sample(["MediaRenderer", "InternetGatewayDevice", "dial", "WFADevice"], rng.randrange(0, 4))
        elif r < 0.65:
            info["types"] = None
        info["name"] = pick(LABELS)
        upnp[ip] = info
    r = rng.random()
    offers = None if r < 0.15 else [] if r < 0.3 else [rand_offer() for _ in range(rng.randrange(1, 4))]
    if offers and rng.random() < 0.03:
        offers.append(None)
    via = {ip: {"ip": pick(IPS + [None]), "name": pick(LABELS), "mac": pick(MACS[:5])} for ip in rng.sample(IPS, rng.randrange(0, 4))}
    names = {ip: pick(LABELS) for ip in rng.sample(IPS, rng.randrange(0, 3))}
    types_arg = pick([None, {}, {"x": ["y"]}])
    try:
        res = ser(roles._build_roles_result(via, names, types_arg, offers, by_ip, upnp))
    except Exception as exc:
        res = ser(exc)
    return {"res": res, "arg": ser(by_ip) if rng.random() < 0.02 else None}


def run_record():
    discover = rng.random() < 0.7
    upnp, arp = pick([{}, {"a": 1}]), pick([{}, {"b": 2}])
    r = rng.random()
    if r < 0.12:
        third = pick([RuntimeError("boom"), ValueError("v")])
    elif r < 0.25:
        third = []
    else:
        third = [rand_offer() for _ in range(rng.randrange(1, 4))]
        if rng.random() < 0.15:  # several servers
            third.append({"server": third[0].get("server", "192.168.1.1") + "9"})
        if rng.random() < 0.15:
            third.append({"server": third[0].get("server", "192.168.1.1")})
    results = [upnp, arp, third] if (rng.random() < 0.97 or not discover) else [upnp, arp]
    if rng.random() < 0.1:
        results = results[:2] + ([third] if not discover else [])
    roles._rt.offers.clear()
    roles._rt.offers.update(list=[{"old": 1}], ts=-1.0)
    roles._rt.on_alert = fake_on_alert if rng.random() < 0.75 else None
    LOG.clear()
    try:
        res = ser(roles._record_dhcp_offers(discover, results))
    except Exception as exc:
        res = ser(exc)
    return {"res": res, "offers": ser(roles._rt.offers), "log": list(LOG)}


def rand_result():
    res = {}
    ips = rng.sample(IPS, rng.randrange(0, 5))
    res["by_ip"] = {ip: {r: pick(SOURCES) for r in rng.sample(roles.ROLE_ORDER, rng.randrange(0, 4))} for ip in ips}
    res["via"] = {ip: {"ip": pick(IPS), "name": None, "mac": "aa"} for ip in rng.sample(IPS, rng.randrange(0, 4))}
    res["names"] = {ip: pick(LABELS) for ip in rng.sample(IPS, rng.randrange(0, 3))}
    res["dhcp"] = [{"server": pick(IPS)}] if rng.random() < 0.4 else []
    res["types"] = {pick(IPS): ["dial"]} if rng.random() < 0.3 else {}
    return res


def run_store():
    result = rand_result()
    r = rng.random()
    before = json.loads(json.dumps(result)) if r < 0.4 else rand_result()
    # equal content, different key order
    if r < 0.2:
        before["by_ip"] = dict(reversed(list(before["by_ip"].items())))
    elif 0.4 <= r < 0.55:
        for k in ("by_ip", "via", "names", "dhcp", "types"):
            if rng.random() < 0.5:
                before[k] = result[k]
    keys = pick([("by_ip", "via", "names", "dhcp", "types"), ("by_ip",), ("via", "dhcp"), (), ("names", "types")])
    if rng.random() < 0.03:
        result.pop("via", None)
    if rng.random() < 0.03:
        before.pop("names", None)
    roles._rt.roles.clear()
    roles._rt.roles.update({"by_ip": {"s": {}}, "via": {}, "names": {}, "types": {}, "dhcp": [], "ts": 0})
    roles._rt.internet["data"] = pick([None, {"cgnat": True}])
    roles._rt.on_change = fake_on_change if rng.random() < 0.7 else None
    now = float(rng.randrange(1, 1000))
    LOG.clear()
    try:
        res = ser(roles._store_roles_and_notify(result, now, keys, before))
    except Exception as exc:
        res = ser(exc)
    return {"res": res, "state": ser(roles._rt.roles), "result": ser(result), "log": list(LOG)}


def run_case(i):
    kind = i % 4
    return [run_find, run_build, run_record, run_store][kind]()


out = [run_case(i) for i in range(N)]
digests = [hashlib.sha1(json.dumps(o).encode()).hexdigest() for o in out]
sample = out[:24]
doc = {"digests": digests, "sample": sample}
if os.environ.get("ROLES_HELPERS_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(doc, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want["digests"]) == len(digests) == N
for i, (x, y) in enumerate(zip(digests, want["digests"])):
    assert x == y, "case %d differs: %s" % (i, json.dumps(out[i])[:600])
assert json.loads(json.dumps(sample)) == want["sample"]

# the scenarios are varied enough
find = [o for i, o in enumerate(out) if i % 4 == 0]
rec = [o for i, o in enumerate(out) if i % 4 == 2]
sto = [o for i, o in enumerate(out) if i % 4 == 3]
bld = [o for i, o in enumerate(out) if i % 4 == 1]
assert sum(1 for o in find if any(l[0] == "add" for l in o["log"])) > 100, "too few repeater roles added"
assert sum(1 for o in find if isinstance(o["res"], dict) and o["res"].get("d")) > 200
assert sum(1 for o in find if o["res"] == {"exc": "AttributeError"}) >= 1
assert sum(1 for o in find if any(isinstance(l[0], str) and l[0] == "add" for l in o["log"]) and o["by_ip"] != o["before"]) > 50
assert sum(1 for o in rec if any(l[0] == "alert" for l in o["log"])) > 30
assert sum(1 for o in rec if any(l[0] == "journal" for l in o["log"])) > 200
assert sum(1 for o in rec if any(l[0] == "log" and l[1] == "warning" for l in o["log"])) > 30
assert sum(1 for o in rec if o["res"] == {"exc": "KeyError"} or o["res"] == {"exc": "IndexError"} or o["res"] == {"exc": "TypeError"}) >= 1
assert sum(1 for o in sto if any(l[0] == "change" for l in o["log"])) > 100
assert sum(1 for o in sto if o["log"] == []) > 100
assert sum(1 for o in sto if o["res"] == {"exc": "KeyError"}) >= 1
assert sum(1 for o in bld if isinstance(o["res"], dict) and "d" in o["res"] and o["res"]["d"][3][1]["d"] == []) > 20
assert sum(1 for o in bld if o["res"] == {"exc": "AttributeError"}) >= 1
print("TUTTO OK")
