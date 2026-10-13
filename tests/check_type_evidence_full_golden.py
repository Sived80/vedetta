"""Golden-master test of ha_type_evidence.type_evidence from end to end: 4000 generated devices - names, brands and vendors made of the words of the rules and of the types of the data files, the declared
model, mDNS services and UPnP types, the answering API, ONVIF and RTSP, scanned ports (confirmed or not, typical, shared, PC ports, IoT-only), network roles, Home Assistant integrations and entities, the
adapter, `kinds_out` given or not - must give exactly the clues (group, family, points, source, in order), the `kinds_out` dictionary and the points per category stored in tests/golden/type_evidence_full.json
(a short digest per device plus a readable sample), written from the code as it was before the chain of stage functions (each handing the next one its half-built state) became one small class. The roles object
and the table of Home Assistant integrations are replaced by in-memory ones that RECORD their calls, so the calls and their order are part of what is compared.
Regenerate only on purpose:  TYPE_EVIDENCE_FULL_GOLDEN_UPDATE=1 python tests/check_type_evidence_full_golden.py"""
import hashlib
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import ha_type_evidence as T  # noqa: E402
from app.ha import ha_type_text as X  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "type_evidence_full.json"
N = 4000
rng = random.Random(20261010)
LOG: list = []


def pick(seq):
    return seq[rng.randrange(len(seq))]


def subset(seq, p):
    return [x for x in seq if rng.random() < p]


class FakeRoles:
    def __init__(self, upnp, roles):
        self.upnp, self.roles = upnp, roles

    def upnp_types(self, ip):
        LOG.append(["upnp_types", ip])
        return self.upnp

    def roles_for(self, ip):
        LOG.append(["roles_for", ip])
        return self.roles


HA_TABLE = {"onvif": {"group": "media", "kind": "camera"}, "braviatv": {"group": "media"}, "shelly": {"platform": True, "group": "iot"}, "esphome": {"platform": True, "group": "iot", "kind": "esp"},
            "hue": {"group": "iot", "kind": "light"}, "empty": {}, "sonos": {"group": "audio", "kind": "speaker"}}
HA_DOMAINS = list(HA_TABLE) + ["daikin", "broadlink", "sonoff"]


def fake_integrations():
    LOG.append(["ha_integrations"])
    return HA_TABLE


T._ha_integrations = fake_integrations

KINDS = T._kinds()
RULE_WORDS = [w for r in X.rules().values() for w in list(r["subs"]) + sorted(r["toks"])]
KIND_WORDS = [w for k in KINDS for w in list(k["subs"]) + sorted(k["toks"])]
BRANDS = sorted({b for k in KINDS for b in k["brands"]})
MDNS = list(T._MDNS_TYPE) + sorted({s for k in KINDS for s in k["mdns"]}) + ["_unknown._tcp", "_zzz._udp"]
UPNP = list(T._UPNP_TYPE) + sorted({s for k in KINDS for s in k["upnp"]}) + ["Basic"]
ROLES = ["gateway", "router", "ap", "repeater", "dhcp", "dns", "client"]
PORTS = sorted(set(T._PORT_TYPE) | set(T._PORT_SHARED) | set(X._PC_PORTS) | {80, 443, 22, 8080, 5353, 49152})
APIS = [None, "", "shelly", "tasmota", "esphome", "cast", "roku", "sonos", "other"]
ENTITY = [None, [], ["device_tracker"], ["sensor"], ["media_player"], ["camera", "light"], ["device_tracker", "switch"], ["climate", "cover"], ("sensor",)]


def words(n):
    pool = pick([RULE_WORDS, KIND_WORDS, KIND_WORDS + RULE_WORDS, ["zzz", "plain"]])
    return " ".join(pick(pool) for _ in range(rng.randrange(0, n + 1)))


def device_case():
    d = {"ip": pick(["10.0.0.5", None, ""])}
    if rng.random() < 0.8:
        d["name"] = pick([words(3), words(1), "Device-1", "", None])
    if rng.random() < 0.2:
        d["name_generated"] = True
    if rng.random() < 0.5:
        d["brand"] = pick(BRANDS + [None, "", "Nobrand"] if BRANDS else [None, ""])
    if rng.random() < 0.4:
        d["vendor"] = pick(BRANDS + ["Espressif", "Nobody"] if BRANDS else ["Espressif"])
        d["vendor_role"] = pick(["brand", "chip", None])
    extra = {}
    if rng.random() < 0.5:
        extra["model"] = pick([words(2), "lumi.camera.acn007", "C200 Camera", ""])
    if rng.random() < 0.2:
        extra["upnp_model"] = words(2)
    if rng.random() < 0.15:
        extra["ha_model"] = words(2)
    if rng.random() < 0.2:
        extra["mdns_model"] = pick(["Google Home Mini", "Nest Hub Max", "Chromecast", "Chromecast Ultra", "Nest Audio", "xyz"])      # product signatures
    if rng.random() < 0.1:
        extra["ha_area"] = words(2)
    if rng.random() < 0.6:
        svcs = subset(MDNS, pick([0.03, 0.1, 0.3]))
        rng.shuffle(svcs)
        extra["mdns_services"] = pick([",".join(svcs), ", ".join(svcs), ",".join(svcs) + ",", ""])
    if rng.random() < 0.5:
        extra["api_source"] = pick(APIS)
    for k in ("onvif_name", "onvif_hardware", "onvif_manufacturer"):
        if rng.random() < 0.06:
            extra[k] = pick(["cam", "", None])
    if rng.random() < 0.12:
        extra["wsd_types"] = pick(["", "wsdp:NetworkVideoTransmitter", "Printer"])
    if rng.random() < 0.12:
        extra["rtsp_server"] = pick([True, False, "rtsp"])
    mode = pick(["extra", "extra", "extra", "none", "empty", "missing"])
    if mode == "extra":
        d["extra"] = extra
    elif mode == "none":
        d["extra"] = None
    elif mode == "empty":
        d["extra"] = {}
    if rng.random() < 0.7:
        ports = []
        for _ in range(pick([0, 1, 2, 4, 8])):
            port = pick(PORTS)
            p = {"label": pick(["%d/tcp http" % port, "%d" % port, "%d/tcp" % port, "", None])}
            if rng.random() < 0.5:
                p["confirmed"] = pick([True, False])
            ports.append(p)
        d["scanned_ports"] = pick([ports, ports, None, []])
    haset = pick(["full", "full", "domains_only", "none", "missing"])
    if haset in ("full", "domains_only"):
        card = {"domains": pick([None, [], subset(HA_DOMAINS, 0.2), ["onvif"], ["daikin"], ["hue", "shelly"], ["empty"]])}
        if haset == "full":
            card["entity_domains"] = pick(ENTITY)
        d["ha_registry"] = card
    elif haset == "none":
        d["ha_registry"] = None
    adapter = pick([None, "", "shelly", "shelly_plus", "tasmota", "esphome"])
    kinds_out = pick([None, {}, {"camera": 1}, {"tv": 5, "x": 2}])
    return d, adapter, kinds_out, FakeRoles(subset(UPNP, pick([0, 0.1, 0.3])), subset(ROLES, pick([0, 0.1, 0.3])))


digests, sample, stats = [], [], {"ev": 0, "ha": 0, "kinds_out": 0, "ports": 0, "iot_only": 0, "platform": 0, "sig": 0, "exception": 0, "empty": 0}
for i in range(N):
    device, adapter, kinds_out, fake_roles = device_case()
    start_kinds = json.loads(json.dumps(kinds_out)) if kinds_out is not None else None
    T.roles = fake_roles
    LOG.clear()
    try:
        ev = T.type_evidence(device, adapter, kinds_out)
        result = {"ev": ev, "kinds_out": kinds_out, "scores": T._aggregate(ev), "log": list(LOG)}
    except Exception as exc:
        result = {"exception": type(exc).__name__}
    text = json.dumps(result, sort_keys=True, default=str)
    digests.append(hashlib.sha1(text.encode("utf-8")).hexdigest()[:10])
    if i % 400 == 0:
        sample.append({"device": device, "adapter": adapter, "kinds_out_in": start_kinds, "result": result})
    if "exception" in result:
        stats["exception"] += 1
        continue
    fam = {e["family"] for e in ev}
    stats["ev"] += bool(ev)
    stats["empty"] += not ev
    stats["ha"] += any(f in ("ha", "ha_entities") for f in fam)
    stats["kinds_out"] += kinds_out is not None and kinds_out != start_kinds
    stats["ports"] += any(f.startswith("port") for f in fam)
    stats["iot_only"] += "port:iot" in fam
    stats["platform"] += "platform" in fam
    stats["sig"] += any(f.startswith("sig:") for f in fam)
got = {"digests": digests, "sample": sample}
if os.environ.get("TYPE_EVIDENCE_FULL_GOLDEN_UPDATE"):
    GOLDEN.parent.mkdir(exist_ok=True)
    GOLDEN.write_text(json.dumps(got, indent=0, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print("golden written:", stats)
    sys.exit(0)
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
bad = [i for i, (a, b) in enumerate(zip(digests, want["digests"])) if a != b]
assert not bad and len(digests) == len(want["digests"]), "type_evidence differs from the golden at devices %s" % bad[:10]
assert json.loads(json.dumps(sample, sort_keys=True, default=str)) == json.loads(json.dumps(want["sample"], sort_keys=True, default=str))
for key, low in (("ev", 3000), ("ha", 150), ("kinds_out", 400), ("ports", 800), ("platform", 100)):
    assert stats[key] >= low, ("the generator no longer reaches this case", key, stats)
print("TUTTO OK", stats)
