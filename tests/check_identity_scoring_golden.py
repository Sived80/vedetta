"""Golden-master test of three public functions of recognition/identity.py, written from the code as it was before their helpers were written back into them: default_gateway (the file reader is replaced
by an in-memory one: system path or not, missing file, header only, malformed or short rows, undecodable data, gateway flag, the cache of the first answer; the calls to `open` and the lines consumed are
compared too), mobile_assess (the score and the reason from every clue: the DHCP score, the name, the model class, the presence, the rotating MAC, the mobile service, the vetoes) and identify_brand
(`lookup_vendor`, `is_private_mac`, `normalize_brand` and the `brands` module are replaced by deterministic fakes driven by the case: every call, its arguments and ORDER are recorded, so a changed
short-circuit shows up). 5000 generated cases per function must give exactly the results stored in tests/golden/identity_scoring.json (exceptions included, by type; key order counts).
Regenerate only on purpose:  IDENTITY_SCORING_GOLDEN_UPDATE=1 python tests/check_identity_scoring_golden.py"""
import json
import os
import random
import sys
import types
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import procfs  # noqa: E402
from app.recognition import identity  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "identity_scoring.json"
N = 5000
rng = random.Random(97531)
LOG: list = []
CASE: dict = {}


def pick(seq):
    return seq[rng.randrange(len(seq))]


def dumps(x):
    return json.dumps(x, default=repr)


def run(fn, *args, **kwargs):
    """Result as JSON-safe data, or the exception type; the recorded calls are returned too."""
    del LOG[:]
    try:
        res = fn(*args, **kwargs)
        out = {"res": res}
    except Exception as exc:  # noqa: BLE001
        out = {"exc": type(exc).__name__}
    out["calls"] = list(LOG)
    return json.loads(dumps(out))


# ------------------------------------------------------------------ fakes
MACS = ["00:11:22:33:44:55", "02:11:22:33:44:55", "da:11:22:33:44:55", "f6:00:00:00:00:01", "a0:ab:cd:00:00:01", None, ""]


def _priv(mac):
    return bool(mac) and mac[1] in "26aeAE"


def fake_mobile_score(mac, name_is_mobile, has_ports):
    LOG.append(["mobile_score", mac, name_is_mobile, has_ports])
    return CASE["ms"]


def fake_dhcp_private(mac):
    LOG.append(["dhcp.is_private_mac", mac])
    return _priv(mac)


def fake_is_private(mac):
    LOG.append(["is_private_mac", mac])
    return _priv(mac)


def fake_lookup(mac):
    LOG.append(["lookup_vendor", mac])
    return CASE["lookup"]


def fake_normalize(raw):
    LOG.append(["normalize_brand", raw])
    return " ".join(w.capitalize() for w in str(raw).split()) or None


KNOWN = {"sony": "Sony", "acme": "Acme"}


def fake_known(v):
    LOG.append(["known_brand", v])
    return KNOWN.get(str(v).strip().lower())


def fake_resolve(vendor, **kw):
    LOG.append(["resolve", vendor, kw])
    return CASE["found"]


identity.dhcp = types.SimpleNamespace(mobile_score=fake_mobile_score, is_private_mac=fake_dhcp_private)
identity.lookup_vendor = fake_lookup
identity.is_private_mac = fake_is_private
identity.normalize_brand = fake_normalize
identity.brands = types.SimpleNamespace(resolve=fake_resolve, known_brand=fake_known)


class FakeFile:
    def __init__(self, items):
        self.items, self.consumed = list(items), 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return self

    def __next__(self):
        if self.consumed >= len(self.items):
            raise StopIteration
        item = self.items[self.consumed]
        self.consumed += 1
        if isinstance(item, Exception):
            raise item
        return item


FILES: dict = {}
OPENED: list = []


def fake_open(path, encoding=None, errors=None):
    LOG.append(["open", path, encoding])
    if path not in FILES:
        raise FileNotFoundError(path)
    f = FakeFile(FILES[path])
    OPENED.append(f)
    return f


procfs.open = fake_open          # the lines of the route file are read by the shared reader, which opens the file (the calls logged stay path and encoding)


# ------------------------------------------------------------------ default_gateway
HEADER = "Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\n"


def route_row():
    return pick([
        "eth0\t00000000\t0102A8C0\t0003\t0\t0\t100\t00000000\n",
        "eth0\t00000000\t0101A8C0\t0003\t0\t0\t100\t00000000\n",
        "eth0\t00000000\t0102A8C0\t0001\t0\t0\t100\t00000000\n",      # no gateway flag
        "eth0\t00000000\t0A00000A\t0002\t0\t0\t100\t00000000\n",      # flag 2 only
        "eth0\t00000000\t0A00000A\t0007\t0\t0\t100\t00000000\n",
        "eth0\t0001A8C0\t0102A8C0\t0003\t0\t0\t100\t00000000\n",      # not the default destination
        "eth0\t00000000\tZZ\t0003\t0\t0\t100\t00000000\n",            # bad hex of the address
        "eth0\t00000000\t0102A8C0\tQQ\t0\t0\t100\t00000000\n",        # bad hex of the flags
        "eth0\t00000000\t1FFFFFFFF\t0003\t0\t0\t100\t00000000\n",     # too large for 4 bytes
        "eth0\t00000000\t0102A8C0\n",                                  # three columns, no flags
        "eth0\t00000000\n", "eth0\n", "\n", "   \n", "",
        "eth1\t0000A8C0\t00000000\t0001\t0\t0\t0\t00FFFFFF\n",
    ])


def route_file():
    items = [] if rng.random() < 0.08 else [HEADER]
    for _ in range(rng.randrange(0, 6)):
        items.append(route_row())
    if rng.random() < 0.1:
        items.insert(rng.randrange(len(items) + 1), pick([UnicodeDecodeError("ascii", b"\xff", 0, 1, "ordinal not in range"), OSError("io"), ValueError("v")]))
    return items


def gateway_case():
    FILES.clear()
    del OPENED[:]
    paths = ["/proc/net/route", "/proc/net/route", "/tmp/route_a", "/tmp/route_b", "/missing/route"]
    for p in paths[:4]:
        if rng.random() < 0.85:
            FILES[p] = route_file()
    identity._gateway_cache["value"] = pick([identity._NO_GATEWAY, identity._NO_GATEWAY, "10.9.9.9"])
    calls = [pick(paths) for _ in range(rng.randrange(1, 4))]
    results = []
    for p in calls:
        r = run(identity.default_gateway) if p == "/proc/net/route" and rng.random() < 0.5 else run(identity.default_gateway, p)
        results.append(r)
    cache = identity._gateway_cache["value"]
    return {"calls": calls, "results": results, "cache": "NO" if cache is identity._NO_GATEWAY else cache, "consumed": [f.consumed for f in OPENED]}


# ------------------------------------------------------------------ mobile_assess
def mobile_case():
    CASE["ms"] = (rng.randrange(-4, 8), pick([None, "", "nome", "MAC privato", "dhcp", "presence"]))
    kwargs = dict(mac=pick(MACS), name_is_mobile=pick([True, False, None, 1, 0]), has_ports=pick([None, True, False]), name_weak=pick([True, False, None, 1, 0]),
                  model_class=pick([None, None, "mobile", "laptop", "fixed", "other", ""]), churn=pick([0, 1, 5, 6, 7, 13, 14, 15, 40, 0, 6, 14, -1, None]),
                  mobile_service=pick([True, False, None, 0, 1, ""]), media_receiver=pick([True, False, None, 0, 1, ""]), mac_changes=pick([0, 1, 2, 3, 0, 2, None]),
                  battery=pick(["yes", "no", None, "YES", "yes"]), battery_source=pick(["api", "scan", "hint", "model", None, "API"]))
    return {"ms": CASE["ms"], "kwargs": kwargs, "out": run(identity.mobile_assess, **kwargs)}


# ------------------------------------------------------------------ identify_brand
def brand_case():
    CASE["lookup"] = pick([None, None, "", "Sony", "Acme", "Foo"])
    brand = pick([None, "", "Sony", "Acme", "Sony", "Acme", "Other"])
    CASE["found"] = {"brand": brand, "source": pick([None, "declared", "oui", "oui", "name", "web", "dhcp"]),
                     "role": pick([None, "", "brand", "brand", "dual", "component", "virtual"]), "confidence": pick([None, "high", "low"])}
    mac = pick(MACS)
    raw_vendor = pick([None, "", "  acme corp ", "Sony Corp"])
    upnp = pick([None, "", "Sony", " acme ", "IPCAM"])
    declared = pick([(), [], ("Sony",), ["IPCAM", "acme"], ("", None, "Foo"), ("Foo",), (" SONY ", "Acme"), None if rng.random() < 0.1 else ()])
    names = pick([(), ["a"], ("Sony TV", "x"), [], None if rng.random() < 0.1 else ("n",)])
    kwargs = dict(names=names, upnp_manufacturer=upnp, declared=declared, web_text=pick([None, "page"]), os_family=pick([None, "linux"]), is_gateway=pick([True, False]), raw_vendor=raw_vendor)
    out = run(identity.identify_brand, mac, **kwargs)
    info = None
    if "res" in out:
        priv = _priv(mac)
        found, bnd = CASE["found"], CASE["found"]["brand"]
        role = found["role"] or ("private" if priv else None)
        decl = {KNOWN.get(str(v).strip().lower()) for v in (upnp, *declared) if v}
        if bnd:
            vend = out["res"]["vendor"]
            flags = [found["source"] == "declared", bnd in decl, found["source"] == "oui" and role == "brand" and not priv,
                     role == "brand" and not priv and KNOWN.get(str(vend).strip().lower()) == bnd]
            info = [i for i, v in enumerate(flags) if v]
    return {"lookup": CASE["lookup"], "found": CASE["found"], "mac": mac, "kwargs": kwargs, "out": out, "info": info}


def build():
    cases = {"gateway": [], "mobile": [], "brand": []}
    for _ in range(N):
        cases["gateway"].append(gateway_case())
        cases["mobile"].append(mobile_case())
        cases["brand"].append(brand_case())
    return cases


cases = build()
info = [c.pop("info") for c in cases["brand"]]
got = [dumps(c) for k in cases for c in cases[k]]
if os.environ.get("IDENTITY_SCORING_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(got), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want) == len(got) == 3 * N
for i, (x, y) in enumerate(zip(got, want)):
    assert x == y, "case %d differs: %s <> %s" % (i, x[:400], y[:400])

# the scenarios must be varied enough to catch a changed condition
g = cases["gateway"]
firsts = [r for c in g for r in c["results"]]
assert sum(1 for r in firsts if r.get("res")) > 1500 and sum(1 for r in firsts if "res" in r and r["res"] is None) > 800, "gateway too uniform"
exc = {r["exc"] for r in firsts if "exc" in r}
assert {"IndexError", "OverflowError"} <= exc, exc
assert sum(1 for c in g if c["cache"] != "NO") > 800 and sum(1 for c in g if any(c["consumed"])) > 2000
assert any(c["cache"] == "10.9.9.9" for c in g)
mo = [c["out"] for c in cases["mobile"]]
mres = [o["res"] for o in mo if "res" in o]
assert sum(1 for r in mres if r["mobile"]) > 800 and sum(1 for r in mres if not r["mobile"]) > 800, "mobile_assess too uniform"
reasons = {r["reason"] for r in mres}
assert {"MAC privati diversi", "servizio mobile", "presence", "model", "nome"} <= reasons, reasons
assert sum(1 for o in mo if "exc" in o) > 5
br = [c["out"] for c in cases["brand"]]
ev = [o["res"]["brand_evidence"] for o in br if "res" in o]
assert ev.count("confirmed") > 800 and ev.count("plausible") > 400 and ev.count(None) > 800 and sum(1 for o in br if "exc" in o) > 100
for clause in range(4):
    assert sum(1 for i in info if i == [clause]) > 15, "clause %d is rarely the only one that holds" % clause
assert any(o["res"]["vendor_role"] == "private" for o in br if "res" in o) and any(o["res"]["vendor"] == "Acme Corp" for o in br if "res" in o)
print("TUTTO OK")
