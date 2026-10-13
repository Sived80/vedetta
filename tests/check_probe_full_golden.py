"""Golden-master test of probe_device as a whole with the sources of evidence (identity, battery, mobile score, Home Assistant, Bonjour, DHCP, network roles) replaced by recorders: 4000 generated
devices - adapters that answer or not, ARP that rescues or not, saved scan info rich or empty, names user-chosen / automatic / placeholders / from Home Assistant, brands declared and chosen by hand,
phones, media receivers, many open ports - must give exactly the same record AND make exactly the same calls to the recorders (arguments included, in order) as the code before the steps of probe_device
were restructured; digests and a readable sample are stored in tests/golden/probe_full.json.
Regenerate only on purpose:  PROBE_FULL_GOLDEN_UPDATE=1 python tests/check_probe_full_golden.py"""
import asyncio
import hashlib
import json
import os
import random
import sys
import tempfile
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()      # never the real folder of the developer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import dhcp, mdns_listener, probe  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "probe_full.json"
N = 4000
rng = random.Random(555)
LOG: list = []
ENV: dict = {}


def pick(seq):
    return seq[rng.randrange(len(seq))]


def jcopy(x):
    return json.loads(json.dumps(x, default=str, sort_keys=True))


def rec(name, fn):
    def f(*args, **kwargs):
        res = fn(*args, **kwargs)
        LOG.append([name, jcopy(list(args)), jcopy(kwargs), jcopy(res)])
        return res
    return f


MACS = [None, "", "b8:27:eb:11:22:33", "B8:27:EB:11:22:33", "f0:18:98:aa:bb:cc", "aa:bb:cc:dd:ee:01", "AA:BB:CC:DD:EE:01", "da:a1:19:11:22:33"]
NAMES = [None, "", "Kitchen camera", "iPhone-di-Anna", "Android_1MRKG1M7", "Galaxy S23", "esp32-sensor", "Pixel-7", "{ip}", "Android", "TV salotto", "Milesight-cam"]
MODELS = [None, "", "SmartTV X1", "iPhone15,2", "AirCast", "HS100", "Hue Bridge", "MS-C2961", "MediaRenderer", "Chromecast"]
MFRS = [None, "", " ", "Apple", "Signify", "Espressif", "Shelly", "Xiaomi", "  Google  "]
TITLES = [None, "", "Router login", "Web UI", "Camera 1.2.3", "OpenWrt - LuCI"]
SERVICES = [None, "", "_googlecast._tcp", "_http._tcp, _amzn-wplay._tcp", "_nearbypresence._tcp", "_http._tcp", "_apple-mobdev2._tcp"]
PORTS = [None, [], [{"port": 80, "label": "nginx", "confirmed": True}], [{"port": 8008, "label": "Android TV", "confirmed": True}, {"port": 22}], [{"port": 443, "label": None}], [{"port": 554, "label": "rtsp"}, {"port": 80}]]
SOURCES = [None, "user", "ha", "ha_user", "web", "mdns", "dhcp", "adapter", "bogus"]
BRANDS = [None, "Apple", "Shelly", "Samsung", "Fairphone", "Philips", "Milesight"]
KINDS = [None, "camera", "phone", "tv", "speaker", "ha"]


def scan_info():
    d = {}
    for k, vals in (("http_title", TITLES), ("mdns_model", MODELS), ("mdns_name", NAMES), ("mdns_manufacturer", MFRS), ("upnp_model", MODELS), ("upnp_name", NAMES), ("onvif_hardware", MODELS), ("api_model", MODELS),
                    ("netbios_name", NAMES), ("onvif_name", NAMES), ("api_name", NAMES), ("upnp_manufacturer", MFRS), ("api_vendor", MFRS), ("onvif_manufacturer", MFRS), ("http_server", ["nginx", None, ""]),
                    ("rtsp_server", ["x", None]), ("tls_subject", ["CN=a.local", "CN=b", None]), ("tls_issuer", ["CN=ca", None]), ("ssh_hostkey", ["k", None]), ("api_fw", ["1.0", None]), ("snmp_descr", ["Linux", None]),
                    ("mdns_services", SERVICES), ("igmp_groups", ["239.0.0.1", None]), ("battery", [None, 40, 0]), ("ports", PORTS), ("scanned_at", [None, 0, 1700000000]), ("deep_empty_at", [None, 5]),
                    ("slow_scan", [True, None])):
        if rng.random() < 0.3:
            d[k] = pick(vals)
    return d


async def fake_adapter(ip, port):
    LOG.append(["adapter", ip, port])
    r = ENV["adapter"]
    if isinstance(r, Exception):
        raise r
    return dict(r) if isinstance(r, dict) else r


probe.ADAPTERS["fake"] = fake_adapter
mdns_listener.lookup = rec("mdns.lookup", lambda mac, ip: ENV["mdns"])
mdns_listener.as_scan_info = rec("mdns.as_scan_info", lambda entry: ENV["remembered"])
dhcp.os_family = rec("dhcp.os_family", lambda mac: ENV["os"])
probe.ha_registry.lookup = rec("ha.lookup", lambda mac, ip=None: ENV["card"])
probe.ha_registry.choose_name = rec("ha.choose_name", lambda card: ENV["ha_choice"])
probe.identify_brand = rec("identify_brand", lambda mac, **kw: dict(ENV["ident"]))
probe.match_model = rec("match_model", lambda texts: ENV["model_class"])
probe.battery_assess = rec("battery_assess", lambda **kw: (ENV["battery"], ENV["battery_source"]))
probe.mobile_assess = rec("mobile_assess", lambda **kw: {"mobile": ENV["mobile"], "score": ENV["score"], "reason": ENV["reason"]})
probe.presence_churn = rec("presence_churn", lambda i: ENV["churn"])
probe.presence_mac_changes = rec("presence_mac_changes", lambda i: ENV["macch"])
probe.default_gateway = rec("default_gateway", lambda: ENV["gw"])
probe.roles.upnp_types = rec("upnp_types", lambda ip: ENV["upnp"])
from app.scan import probe_names  # noqa: E402
probe_names._roles.roles_for = rec("roles_for", lambda ip: ENV["roles"])
probe_names.roles.snapshot = rec("roles.snapshot", lambda: {"names": ENV["role_names"]})


def scenario(i):
    ip = "10.0.%d.%d" % (i % 3, 10 + i % 150)
    names_for_ip = {ip: pick([None, "role-name", "dns.lan"])} if rng.random() < 0.4 else {}
    ENV.clear()
    ENV.update(
        adapter=pick([{"online": False}, {"online": True}, {"online": True, "mac": pick(MACS), "uptime_seconds": rng.randrange(0, 10**7), "name": pick(NAMES), "battery": pick([None, 80]),
                                                           "extra": {"model": pick(MODELS), "hostname": pick(NAMES), "fw": pick([None, "1.2.3"]), "a": 0, "dhcp_class": pick([None, "from-adapter"])}},
                      {"online": True, "signal_kind": "wifi", "signal_value": rng.randrange(-90, -30), "signal_band": pick(["2.4", "5"])},
                      {"online": False, "mac": pick(MACS), "extra": {}}, RuntimeError("down")]),
        mdns=pick([None, {"n": 1}]), remembered=pick([None, {}, {"mdns_name": pick(NAMES), "mdns_model": pick(MODELS), "mdns_manufacturer": pick(MFRS), "http_title": pick(TITLES)}]), os=pick([None, "ios", "android"]),
        card=pick([None, None, {"manufacturer": pick(MFRS), "model": pick(MODELS), "area": pick([None, "Cucina"]), "domains": pick([None, [], ["hue"], ["mobile_app"], ["mobile_app", "hue"]]), "name": "x"}]),
        ha_choice=pick([(None, None), (None, None), ("Lampada", "ha"), ("Lampada", "ha_user"), ("Kitchen camera", "ha"), ("", "ha")]),
        ident={"brand": pick(BRANDS), "vendor": pick([None, "Espressif", "Apple", "Shelly"]), "vendor_role": pick([None, "component", "maker"]), "brand_source": pick([None, "mac", "declared", "user", "name", "ha"]),
               "brand_confidence": pick(["low", "high"]), "brand_evidence": pick([None, "confirmed", "weak"]), "brand_declared": pick([None, "Acme"])},
        model_class=pick([None, "phone", "camera"]), battery=pick([None, 0, 55]), battery_source=pick([None, "api", "scan"]), mobile=pick([True, False, None]), score=rng.randrange(0, 5),
        reason=pick([None, "name", "ports"]), churn=pick([0, 3, 9]), macch=pick([0, 1, 4]), gw=pick(["10.0.0.1", "10.0.1.10", None]), upnp=pick([[], ["MediaRenderer"], ["dial"], ["x"]]),
        roles=pick([[], ["gateway"], ["dns"], ["repeater", "dns"], ["dhcp"], ["x"]]), role_names=names_for_ip)
    dhcp.seen.clear()
    for m in MACS:
        if m and rng.random() < 0.5:
            dhcp.seen[m.lower()] = pick([{"hostname": pick(NAMES), "vendor_class": pick([None, "", "android-dhcp-13", "MSFT 5.0"])}, {}, None])
    device = {"id": "d%d" % i, "ip": ip, "adapter": pick(["fake", "fake", "fake", "unknown"]), "port": pick([None, 80, 443, 8080]), "name": (pick(NAMES) or "").replace("{ip}", ip) or None,
              "name_source": pick(SOURCES), "last_mac": pick(MACS), "brand_user": pick([None, None, "", "Philips", " Acme "]), "mobile": pick([None, None, None, True, False, 0]),
              "lan_speed_mbps": pick([None, None, 100, 1000]), "scan_info": pick([None, {}, scan_info(), scan_info()])}
    if device["port"] is None:
        del device["port"]
    if rng.random() < 0.4:             # an anonymous device: nothing gives it a name, so the brand, the type and the network role have to
        device["name"] = None
        device["name_source"] = pick([None, "adapter", "dhcp"])
        device["scan_info"] = {k: v for k, v in (device["scan_info"] or {}).items() if k not in ("api_name", "mdns_name", "upnp_name", "netbios_name", "onvif_name", "tls_subject", "http_title")}
        ENV["adapter"] = {k: v for k, v in ENV["adapter"].items() if k != "name"} if isinstance(ENV["adapter"], dict) else ENV["adapter"]
        ENV.update(remembered=None, ha_choice=(None, None), role_names={})
        for m in list(dhcp.seen):
            dhcp.seen[m] = {k: v for k, v in (dhcp.seen[m] or {}).items() if k != "hostname"}
    arp = pick([None, None, {}, {ip: {"mac": pick(MACS)}}, {ip: {}}])
    return device, arp


async def one(i):
    device, arp = scenario(i)
    task = None
    if arp is not None:
        async def arp_view():
            LOG.append(["arp_task"])
            return arp
        task = asyncio.ensure_future(arp_view())
    try:
        rec_ = await probe.probe_device(device, task)
    except Exception as exc:  # noqa: BLE001
        rec_ = {"exception": type(exc).__name__, "text": str(exc)[:80]}
    return {"device": device, "arp": arp, "record": rec_}


out = []
loop = asyncio.new_event_loop()
for i in range(N):
    LOG.clear()
    o = loop.run_until_complete(one(i))
    out.append({**jcopy(o), "log": jcopy(LOG)})


def digest(x):
    return hashlib.sha1(json.dumps(x, default=str, sort_keys=True).encode()).hexdigest()[:20]


result = {"digests": [digest(o) for o in out], "sample": out[:6]}
if os.environ.get("PROBE_FULL_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(result, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want["digests"]) == len(result["digests"]) == N
for i, (x, y) in enumerate(zip(result["digests"], want["digests"])):
    assert x == y, "device %d differs: %s" % (i, json.dumps(out[i], default=str)[:900])
assert result["sample"] == want["sample"]
c = lambda f: sum(1 for o in out if f(o))  # noqa: E731
rc = lambda o: o["record"] if "exception" not in o["record"] else {}  # noqa: E731
stats = {"exc": c(lambda o: "exception" in o["record"]), "online": c(lambda o: rc(o).get("online")), "named_ip": c(lambda o: rc(o).get("name") == o["device"]["ip"]),
         "generated": c(lambda o: rc(o).get("name_generated")), "mobile": c(lambda o: rc(o).get("is_mobile")), "scored": c(lambda o: rc(o).get("mobile_score") is not None),
         "ha_card": c(lambda o: rc(o).get("ha_registry")), "brand_ha": c(lambda o: rc(o).get("brand_source") == "ha"), "brand_user": c(lambda o: rc(o).get("brand_source") == "user"),
         "auto_name": c(lambda o: rc(o).get("auto_name")), "arp_rescue": c(lambda o: o["arp"] and any(e[0] == "arp_task" for e in o["log"]) and rc(o).get("online")),
         "role_name": c(lambda o: any(e[0] == "roles_for" and e[3] for e in o["log"]) and rc(o).get("name_generated")), "signal": c(lambda o: rc(o).get("signal_kind")),
         "title": c(lambda o: "title" in (rc(o).get("extra") or {})), "kept": c(lambda o: rc(o).get("name") not in (None, o["device"]["ip"]))}
for key, low in (("exc", 0), ("online", 1500), ("named_ip", 40), ("generated", 100), ("mobile", 500), ("scored", 1500), ("ha_card", 400), ("brand_ha", 60), ("brand_user", 300), ("auto_name", 600), ("arp_rescue", 100),
                 ("role_name", 15), ("signal", 400), ("title", 300), ("kept", 1500)):
    assert stats[key] >= low, ("scenarios too uniform", key, stats)
print("TUTTO OK")
