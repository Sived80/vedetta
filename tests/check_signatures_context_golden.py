"""Golden-master test of signatures.context (the fields the product signatures are evaluated on, taken from a device in probe format), written from the code as it was before the function
was split into small helpers: 5000 generated devices and UPnP type lists - missing or None "extra", empty and non-string values, scanned ports with labels such as "80/tcp http", " 443 ssl",
"8080", "abc", "", None or missing, malformed port entries, mDNS service strings with spaces, empty items and repeats, HA registry shapes, tuples/lists/None/strings as UPnP types - must give
exactly the results stored in tests/golden/signatures_context.json (exceptions included, by type; the key order of the result counts, sets are written sorted).
Regenerate only on purpose:  SIGNATURES_CONTEXT_GOLDEN_UPDATE=1 python tests/check_signatures_context_golden.py"""
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.recognition import signatures  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "signatures_context.json"
N = 6000
rng = random.Random(8080123)


def pick(seq):
    return seq[rng.randrange(len(seq))]


TEXTS = [None, "", "Chromecast", "nginx/1.2", "Acme TV", 0, "x y", "UPPER", " padded "]
LABELS = ["80/tcp http", " 443 ssl", "8080", "abc", "", None, "22/tcp ssh", "  7000 airplay", "Http 80", "9/udp", "00123", "1e3", "  ", "554/RTSP"]
SERVICES = [None, "", "_googlecast._tcp,_http._tcp", " _a._tcp , _b._tcp ,, ", ",", "_x._tcp,_x._tcp", " ", "a b,c d", "_z._tcp", ",a,", 5, " _a._tcp\t,_b._tcp", "\t,_c._tcp ", "_d._tcp\n", " \t "]
UPNP = [(), [], ["urn:a", "urn:b"], ("urn:a",), None, "ab", ["urn:a", "urn:a"], iter(["it1", "it2"]) if False else ("t",)]
EXTRA_KEYS = ["mdns_model", "upnp_model", "upnp_manufacturer", "dhcp_class", "http_server", "title", "api_source"]


def scanned_port():
    r = rng.random()
    if r < 0.02:
        return pick([None, "80", 5])
    p = {}
    if rng.random() < 0.9:
        p["label"] = pick(LABELS)
    if rng.random() < 0.3:
        p["port"] = rng.randrange(1, 100)
    return p


def device():
    d = {}
    r = rng.random()
    if r < 0.8:
        extra = {}
        for k in EXTRA_KEYS:
            if rng.random() < 0.6:
                extra[k] = pick(TEXTS)
        if rng.random() < 0.7:
            extra["mdns_services"] = pick(SERVICES)
        d["extra"] = extra
    elif r < 0.9:
        d["extra"] = pick([None, {}, ""])
    if rng.random() < 0.7:
        d["brand"] = pick(TEXTS)
    r = rng.random()
    if r < 0.75:
        d["scanned_ports"] = [scanned_port() for _ in range(rng.randrange(0, 6))]
    elif r < 0.85:
        d["scanned_ports"] = pick([None, []])
    r = rng.random()
    if r < 0.6:
        d["ha_registry"] = pick([{"domains": ["light", "switch"]}, {"domains": []}, {"domains": None}, {}, None, {"domains": ("a", "b")}, {"domains": "ab"}, {"x": 1}])
    elif r < 0.65:
        d["ha_registry"] = pick(["text", 3])
    return d


def norm(x):
    if isinstance(x, set):
        return sorted(x)
    return x


def run(d, upnp):
    try:
        res = signatures.context(d, upnp)
        return {"res": {k: norm(v) for k, v in res.items()}, "order": list(res)}
    except Exception as exc:  # noqa: BLE001
        return {"exc": type(exc).__name__}


cases = []
for _ in range(N):
    d, upnp = device(), pick(UPNP)
    cases.append({"device": d, "upnp": upnp, "out": run(d, upnp)})
got = [json.dumps(c) for c in cases]
if os.environ.get("SIGNATURES_CONTEXT_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(got), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want) == len(got) == N
for i, (x, y) in enumerate(zip(got, want)):
    assert x == y, "case %d differs: %s <> %s" % (i, x[:500], y[:500])

res = [c["out"]["res"] for c in cases if "res" in c["out"]]
exc = {c["out"]["exc"] for c in cases if "exc" in c["out"]}
assert len(res) > 4000 and {"AttributeError", "TypeError"} <= exc, (len(res), exc)
assert sum(1 for r in res if r["ports"]) > 2000 and sum(1 for r in res if r["port_labels"]) > 2500 and sum(1 for r in res if len(r["mdns_services"]) > 1) > 500
assert sum(1 for r in res if r["ha_domains"]) > 1000 and sum(1 for r in res if r["upnp_types"]) > 3000 and sum(1 for r in res if r["brand"]) > 2000
assert any(r["ports"] and 0 in r["ports"] for r in res) is False and any(80 in r["ports"] for r in res) and any(123 in r["ports"] for r in res)
assert sum(1 for r in res if r["mdns_model"] and r["upnp_model"] and r["api_source"] and r["title"]) > 20
print("TUTTO OK")
