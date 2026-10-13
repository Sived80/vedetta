"""Golden-master test of ha/device_debug.py device_debug (what debug mode shows for a device): 3000 generated devices and configurations, with every collaborator replaced by a deterministic
in-memory fake that RECORDS ITS CALLS (shared state, ha_data, naming, identity, roles, dhcp, ha_registry, mdns_listener) - missing or blank names and MACs, scan data with falsy values, repeated
and tied evidence, TLS subjects, DHCP entries with a "seen" key, an unknown device id - must give exactly the result (the ORDER of the keys included) and the ORDER and arguments of every call,
stored as a sha1 digest per case plus a small readable sample in tests/golden/device_debug.json, written from the code as it was before the function was split.
Regenerate only on purpose:  DEVDEBUG_GOLDEN_UPDATE=1 python tests/check_device_debug_golden.py"""
import hashlib
import json
import os
import random
import sys
import types
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import device_debug as dd  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "device_debug.json"
N = 3000
rng = random.Random(97531)
STATS: dict = {}


def pick(seq):
    return seq[rng.randrange(len(seq))]


def dig(obj) -> str:
    return hashlib.sha1(json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def count(key, cond):
    STATS[key] = STATS.get(key, 0) + (1 if cond else 0)


NAMES = [None, "", "Living TV", "iPhone di X", "esp-1234"]
RAWS = [None, "", "Shelly-1PM", "my-host.local", "Title page", 0]
SCAN_KEYS = ("scanned_at", "deep_empty_at", "slow_scan", "full_ports_at", "services_at", "mdns_model", "mdns_manufacturer", "mdns_services", "http_server", "http_title", "tls_subject",
             "ssh_hostkey")


def make_case():
    mac = pick([None, "", "AA:BB:CC:00:00:01", "aa:bb:cc:00:00:02", "Aa:Bb:Cc:00:00:03"])
    device = {}
    for key, vals in (("name", NAMES), ("mac", [mac]), ("ip", [None, "10.0.0.5"]), ("brand", [None, "Acme"]), ("brand_source", [None, "mdns"]), ("brand_evidence", [None, ["a", "b"]]),
                      ("brand_confidence", [None, 0.7, 0]), ("brand_declared", [None, "Decl"]), ("vendor", [None, "Vend"]), ("vendor_role", [None, "maker"]), ("is_mobile", [None, True, False]),
                      ("mobile_score", [None, 3, 0]), ("mobile_reason", [None, "churn"]), ("battery", [None, 80]), ("battery_source", [None, "api"])):
        if rng.random() < 0.8:
            device[key] = pick(vals)
    if rng.random() < 0.04:
        device = {}
    if rng.random() < 0.7:
        device["extra"] = pick([None, {}, {"zeta": 1, "alpha": 2, "mid": None}])
    scan = {}
    for key in ("api_name", "mdns_name", "upnp_name", "netbios_name", "onvif_name", "http_title"):
        if rng.random() < 0.6:
            scan[key] = pick(RAWS)
    if rng.random() < 0.5:
        scan["tls_subject"] = pick([None, "", "CN=router.lan", "CN="])
    for key in SCAN_KEYS:
        if rng.random() < 0.5:
            scan[key] = pick([None, 0, "", 1700000000, "x", ["a"]])
    cfg = {}
    for key, vals in (("adapter", [None, "shelly"]), ("type_user", [None, "tv"]), ("name_source", [None, "mdns"]), ("brand_user", [None, "B"]), ("mobile", [None, "yes"]), ("wol_ok", [None, 0, 1, True, "x"])):
        if rng.random() < 0.6:
            cfg[key] = pick(vals)
    if rng.random() < 0.8:
        cfg["scan_info"] = pick([scan, scan, None, {}]) if scan else pick([None, {}])
    if rng.random() < 0.2:
        cfg = None
    evidence = []
    for _ in range(rng.randrange(0, 8)):
        evidence.append({"group": pick(["net", "name", "port"]), "family": pick(["f1", "f2", "f3"]), "pts": pick([0, 1, 2, 2, 3, 5, -1]), "what": pick(["a", "b", "c"])})
    scores = {pick(["tv", "phone", "pc", "cam", "light"]): pick([1, 2, 2, 5, 0, -1]) for _ in range(rng.randrange(0, 6))}
    kinds = {pick(["k1", "k2", "k3", "k4"]): pick([1, 2, 2, 5]) for _ in range(rng.randrange(0, 5))}
    entry_pool = [None, {}, {"hostname": "dhcp-host", "seen": 5, "vendor_class": "android"}, {"seen": 1}, {"hostname": ""}]
    seen = {}
    if mac:
        e = pick(entry_pool)
        if e is not None:
            seen[mac.lower()] = e
    return {"device": device, "cfg": cfg, "evidence": evidence, "scores": scores, "kinds": kinds, "seen": seen, "known": rng.random() < 0.9,
            "cfgmap_has": rng.random() < 0.85, "reg": pick([None, {"area": "x"}]), "mdns": pick([None, {"name": "m"}])}


def run(case):
    log: list = []
    dev_id = "dev1"
    devices = {dev_id: case["device"]} if case["known"] else {}
    cfgmap = {dev_id: case["cfg"]} if case["cfgmap_has"] else {}
    if not case["cfgmap_has"] and rng.random() < 0.0:
        pass

    def rec(name, result):
        def f(*a):
            log.append([name, *a])
            return result(*a) if callable(result) else result
        return f

    def type_evidence(device, adapter, kinds):
        log.append(["type_evidence", device is case["device"], adapter])
        kinds.update(case["kinds"])
        return case["evidence"]

    ha_data = types.SimpleNamespace(
        config_map=rec("config_map", cfgmap), type_evidence=type_evidence, _aggregate=lambda ev: (log.append(["_aggregate", len(ev)]), dict(case["scores"]))[1],
        effective_type=lambda device, cfg: (log.append(["effective_type", device is case["device"], cfg]), "T")[1], MARGIN_BELOW=7, MIN_TYPE_SCORE=11)
    naming = types.SimpleNamespace(clean_name=rec("clean_name", lambda raw: "C(%s)" % raw), cn_host=rec("cn_host", lambda s: "H(%s)" % s) if True else None,
                                   is_placeholder=rec("is_placeholder", lambda n: bool(n) and "esp" in n))
    identity = types.SimpleNamespace(is_private_mac=rec("is_private_mac", lambda m: bool(m) and m[1:2].lower() in "26ae"), presence_churn=rec("presence_churn", 4),
                                     presence_mac_changes=rec("presence_mac_changes", [1, 2]))
    roles = types.SimpleNamespace(roles_for=rec("roles_for", ["r1"]), upnp_types=rec("upnp_types", ["u1"]))
    dhcp = types.SimpleNamespace(seen=case["seen"], os_family=rec("os_family", "android"))
    ha_registry = types.SimpleNamespace(lookup=rec("registry_lookup", case["reg"]))
    mdns_listener = types.SimpleNamespace(lookup=rec("mdns_lookup", case["mdns"]))
    saved = {k: getattr(dd, k) for k in ("state", "ha_data", "naming", "identity", "roles", "dhcp", "ha_registry", "mdns_listener")}
    dd.state, dd.ha_data, dd.naming, dd.identity, dd.roles, dd.dhcp, dd.ha_registry, dd.mdns_listener = (
        types.SimpleNamespace(devices=devices), ha_data, naming, identity, roles, dhcp, ha_registry, mdns_listener)
    try:
        try:
            res = dd.device_debug(dev_id)
            out = {"res": res, "keys": list(res) if res else None}
        except Exception as exc:
            out = {"exc": type(exc).__name__}
    finally:
        for k, v in saved.items():
            setattr(dd, k, v)
    out["log"] = log
    r = out.get("res")
    count("none", "res" in out and r is None)
    count("full", bool(r))
    count("exc", "exc" in out)
    if r:
        count("cands", len(r["name"]["candidates"]) >= 3)
        count("ties", any(not e["counted"] for e in r["type"]["evidence"]))
        count("tls", any(c["source"] == "tls" for c in r["name"]["candidates"]))
        count("dhcp", bool(r["dhcp"]))
        count("scan", len(r["scan"]) >= 3)
        count("extra", bool(r["extra_keys"]))
        count("wol", r["wol"]["ok"])
    return out


res, samples = [], []
for i in range(N):
    r = run(make_case())
    res.append(dig(r))
    if i < 5:
        samples.append(r)
out = json.loads(json.dumps({"digests": res, "samples": samples}, ensure_ascii=False, default=str))
if os.environ.get("DEVDEBUG_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(out, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(out["digests"]) == len(want["digests"]) == N
for i, (x, y) in enumerate(zip(out["digests"], want["digests"])):
    assert x == y, "case %d differs" % i
assert out["samples"] == want["samples"]
s = STATS
assert s["none"] > 100 and s["full"] > 2000 and s.get("exc", 0) == 0, s
for k in ("cands", "ties", "tls", "dhcp", "scan", "extra", "wol"):
    assert s[k] > 150, (k, s)
print("TUTTO OK")
