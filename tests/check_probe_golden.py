"""Golden-master test of probe_device: 300 generated devices (always the same, seeded) go through it with the network faked, and the
whole result of each must match the file tests/golden/probe_device.json, written from the code as it was before the function was split.

It judges nothing: it proves that moving code around leaves every output identical. If a change is meant to alter an output, regenerate
the file on purpose:  PROBE_GOLDEN_UPDATE=1 python tests/check_probe_golden.py   and look at the diff before committing it."""
import asyncio
import json
import os
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import ha_registry  # noqa: E402
from app.scan import dhcp, mdns_listener, probe  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "probe_device.json"
N = 300
NAMES = [None, "", "Kitchen camera", "iPhone-di-Anna", "Android_1MRKG1M7", "{ip}", "Milesight-cam", "Galaxy S23", "esp32-sensor", "TV salotto", "Pixel-7"]
SOURCES = [None, "user", "ha", "ha_user", "web", "mdns", "dhcp"]
MACS = [None, "b8:27:eb:11:22:33", "f0:18:98:aa:bb:cc", "3c:5a:b4:01:02:03", "aa:bb:cc:dd:ee:01", "da:a1:19:11:22:33", "24:0a:c4:55:66:77", "00:17:88:12:34:56"]
MODELS = [None, "iPhone15,2", "Chromecast", "HS100", "SM-S911B", "Hue Bridge", "MS-C2961"]
TITLES = [None, "Router login", "Web UI", "Camera"]
HOSTS = [None, "iphone-di-anna", "esp-1A2B3C", "DESKTOP-ABC123", "Galaxy-S23"]
CLASSES = [None, "android-dhcp-13", "MSFT 5.0", "udhcp 1.31"]
HA_MFR = [None, "Apple", "Signify", "Google", "Shelly"]
rng = random.Random(20261009)
state = {}


async def fake_adapter(ip, port):
    return state["adapter"]


probe.ADAPTERS["fake"] = fake_adapter


def pick(seq):
    return seq[rng.randrange(len(seq))]


def scenario(i):
    ip = "192.168.1.%d" % (10 + i % 200)
    adapter = pick([{"online": False}, {"online": True}, {"online": True, "mac": pick(MACS), "uptime_seconds": rng.randrange(0, 10**7),
                    "extra": {"model": pick(MODELS), "fw": pick([None, "1.2.3"])}},
                    {"online": True, "signal_kind": "wifi", "signal_value": rng.randrange(-90, -30), "signal_band": pick(["2.4", "5"])},
                    {"online": False, "mac": pick(MACS)}])
    arp = pick([None, None, {"mac": pick(MACS)}])
    mdns = pick([None, None, {"name": pick(["Anna iPhone", "Cucina", None]), "model": pick(MODELS), "manufacturer": pick(HA_MFR), "seen": time.time()}])
    dh = pick([None, None, {"hostname": pick(HOSTS), "vendor_class": pick(CLASSES)}])
    ha = pick([None, None, {"name": pick(["Lampada", "shelly1-8CAA11", "iPhone", None]), "name_by_user": pick([True, False]),
                            "manufacturer": pick(HA_MFR), "model": pick(MODELS), "area": pick([None, "Cucina"]),
                            "domains": pick([[], ["hue"], ["mobile_app"], ["shelly", "hue"]])}])
    scan_info = pick([{}, {}, {"http_title": pick(TITLES), "ports": pick([[], [{"port": 80, "open": True}], [{"port": 443}, {"port": 8009}]]),
                      "upnp_name": pick(NAMES[2:5]), "upnp_model": pick(MODELS), "mdns_model": pick(MODELS), "snmp_descr": pick([None, "Linux"]),
                      "scanned_at": 1700000000 + i}])
    device = {"id": "d%d" % i, "ip": ip, "adapter": "fake", "port": pick([80, 443, 8080]), "name": (pick(NAMES) or "").replace("{ip}", ip) or None,
              "name_source": pick(SOURCES), "last_mac": pick(MACS), "scan_info": scan_info, "mobile": pick([None, None, None, True, False]),
              "brand_user": pick([None, None, None, "Philips"]), "lan_speed_mbps": pick([None, None, 100, 1000])}
    return device, adapter, arp, mdns, dh, ha


async def one(i):
    device, adapter, arp, mdns, dh, ha = scenario(i)
    state["adapter"] = adapter
    mdns_listener.by_mac.clear()
    mdns_listener.by_ip.clear()
    if mdns:
        mdns_listener.by_ip[device["ip"]] = mdns
    dhcp.seen.clear()
    for mac in {(adapter.get("mac") or ""), (device["last_mac"] or ""), ((arp or {}).get("mac") or "")} - {""}:
        if dh:
            dhcp.seen[mac.lower()] = dh
    ha_registry.lookup = lambda mac, ip=None: ha

    async def arp_view():
        return {device["ip"]: arp} if arp else {}
    task = asyncio.ensure_future(arp_view())
    return await probe.probe_device(device, task)


def run_all():
    loop = asyncio.new_event_loop()
    return [loop.run_until_complete(one(i)) for i in range(N)]


out = json.loads(json.dumps(run_all(), sort_keys=True, default=str))
if os.environ.get("PROBE_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(out, sort_keys=True, indent=0), encoding="utf-8")
    print("golden written:", GOLDEN)
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want) == len(out) == N
for i, (a, b) in enumerate(zip(out, want)):
    if a != b:
        diff = {k: (a.get(k), b.get(k)) for k in set(a) | set(b) if a.get(k) != b.get(k)}
        raise AssertionError("scenario %d differs: %s" % (i, json.dumps(diff, default=str)[:800]))
names = {o["name"] for o in out}
assert len(names) > 20 and len({o["brand"] for o in out}) > 4 and any(o["is_mobile"] for o in out) and any(o["online"] for o in out), "scenarios too uniform"
print("TUTTO OK")
