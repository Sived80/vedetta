"""Golden-master test of ha_data.type_evidence (the clues that decide the category of a device): 400 generated devices (seeded, always
the same) with the role lookups faked; the evidence list and the per-kind points of each must match tests/golden/type_evidence.json, written
from the code as it was before the function was split. Regenerate only on purpose: TYPE_GOLDEN_UPDATE=1 python tests/check_evidence_golden.py"""
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import ha_data  # noqa: E402
from app.recognition import roles  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "type_evidence.json"
N = 400
rng = random.Random(77)
WORDS = ["camera", "tv", "printer", "router", "nas", "phone", "iphone", "lamp", "plug", "speaker", "chromecast", "hue", "sonos", "shelly", "xiaomi",
         "apple", "samsung", "hp", "synology", "esp32", "tasmota", "raspberry", "thermostat", "doorbell", "sensor", "bridge", "switch", "ap", "laptop", "pc"]
SERVICES = ["_airplay._tcp", "_googlecast._tcp", "_hap._tcp", "_ipp._tcp", "_printer._tcp", "_smb._tcp", "_spotify-connect._tcp", "_http._tcp", "_companion-link._tcp"]
UPNP = ["MediaRenderer", "InternetGatewayDevice", "MediaServer", "Basic", "Printer"]
LABELS = ["80/tcp http", "443/tcp https", "554/tcp rtsp", "22/tcp ssh", "1883/tcp mqtt", "5683/tcp coap", "9100/tcp jetdirect", "445/tcp smb", "8009/tcp castv2", "8883/tcp mqtts"]
DOMAINS = ["hue", "shelly", "cast", "sonos", "mobile_app", "mikrotik", "tplink", "esphome", "unifi"]
ENT = ["light", "switch", "sensor", "media_player", "camera", "device_tracker", "climate"]


def pick(seq):
    return seq[rng.randrange(len(seq))]


def many(seq, k):
    return [pick(seq) for _ in range(rng.randrange(0, k + 1))]


def device(i):
    d = {"ip": "10.0.0.%d" % (i % 250 + 1), "name": " ".join(many(WORDS, 3)) or None, "brand": pick([None, "Apple", "Philips", "TP-Link", "Google"]),
         "vendor": pick([None, "Espressif", "Raspberry Pi", "Samsung Electronics"]), "name_generated": pick([False, False, True]),
         "scanned_ports": [{"label": l} for l in many(LABELS, 4)]}
    extra = {}
    if rng.random() < 0.5:
        extra["mdns_services"] = ",".join(many(SERVICES, 3))
    if rng.random() < 0.2:
        extra["api_source"] = pick(["shelly", "tasmota", "esphome", "cast", "roku", "sonos", "other"])
    if rng.random() < 0.15:
        extra["onvif_name"] = "cam"
    if rng.random() < 0.15:
        extra["rtsp_server"] = "Hikvision"
    if rng.random() < 0.4:
        extra["model"] = " ".join(many(WORDS, 2))
        extra["ha_model"] = " ".join(many(WORDS, 2))
    d["extra"] = extra
    if rng.random() < 0.4:
        d["ha_registry"] = {"domains": many(DOMAINS, 2), "entity_domains": many(ENT, 3), "model": " ".join(many(WORDS, 2))}
    return d, pick([None, None, "shelly", "tasmota", "generic"])


out = []
for i in range(N):
    d, adapter = device(i)
    roles.upnp_types = lambda ip, _u=many(UPNP, 2): list(_u)
    roles.roles_for = lambda ip, _r=pick([[], [], ["gateway"], ["repeater"], ["dhcp"]]): list(_r)
    kinds = {}
    ev = ha_data.type_evidence(d, adapter, kinds)
    out.append({"ev": ev, "kinds": kinds})
out = json.loads(json.dumps(out, sort_keys=True, default=str))
if os.environ.get("TYPE_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(out, sort_keys=True, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
for i, (a, b) in enumerate(zip(out, want)):
    assert a == b, "scenario %d differs: %s" % (i, json.dumps([a, b], default=str)[:600])
assert len(out) == len(want) == N
assert sum(1 for o in out if o["ev"]) > 150 and sum(1 for o in out if o["kinds"]) > 50 and len({e["group"] for o in out for e in o["ev"]}) >= 4, "scenarios too uniform"
print("TUTTO OK")
