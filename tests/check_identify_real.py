"""Name and category of real devices (data read from the network on 2026-10-04): PC with firewall
(no ports), unnamed camera, Proxmox with certificate and page over TLS, TV via UPnP,
Tasmota thermostat. No rule for a specific device: what counts are brand, certificate, title,
services and ports."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import ha_data
from app import i18n
from app.scan import probe
from app.recognition import roles  # noqa: E402

i18n.use("it")
probe.ADAPTERS = {}
roles.roles_for = lambda ip: []
roles.upnp_types = lambda ip: ["MediaRenderer", "dial"] if ip == "10.0.0.113" else []


def p(label, confirmed=False, cat="other"):
    return {"label": label, "confirmed": confirmed, "category": cat}


CASES = [
    # (ip, mac, saved name, scan_info, expected name (substring), expected category)
    ("10.0.0.117", "74:04:F1:00:00:B6", "MSI", {"mdns_name": "MSI", "slow_scan": True}, "MSI", "pc"),
    ("10.0.0.190", "1C:C3:16:00:00:AA", "10.0.0.190",
     {"http_title": "Login", "http_server": "webserver",
      "ports": [p("80 · http", cat="web"), p("554 · rtsp", cat="media"), p("4567 · tram"), p("8000 · http-alt", cat="web"),
                p("34567 · dhanalakshmi")]}, "Milesight telecamera", "media"),
    ("10.0.0.201", "E0:D3:62:00:00:AC", "10.0.0.201",
     {"http_server": "pve-api-daemon/3.0", "http_title": "pve - Proxmox Virtual Environment",
      "tls_subject": "commonName=pve.local/organizationName=Proxmox Virtual Environment",
      "ports": [p("22 · ssh", cat="remote"), p("8006 · wpl-analytics", cat="web")]}, "pve", "server"),
    ("10.0.0.202", "E0:D3:62:00:00:AD", "10.0.0.202",
     {"http_server": "pve-api-daemon/3.0", "ports": [p("22 · ssh", cat="remote"), p("8006 · wpl-analytics", cat="web")]},
     "Proxmox server", "server"),
    ("10.0.0.113", "38:B8:00:00:00:A8", "SONY XR-55X92K",
     {"upnp_name": "SONY XR-55X92K", "upnp_manufacturer": "Sony", "upnp_model": "BRAVIA 4K VH21",
      "mdns_services": "_androidtvremote2._tcp, _airplay._tcp", "ports": [p("8443", cat="other")]}, "SONY", "media"),
    # Home Assistant with AirCast: the proxy announces the name of a Sony TV, but it is not this computer's
    ("10.0.0.100", "BC:24:11:00:00:01", "10.0.0.100",
     {"http_title": "Home Assistant", "mdns_name": "CCCCFE0000B7@SONY XR-55X92K+", "mdns_model": "aircast",
      "mdns_services": "_esphomebuilder._tcp, _home-assistant._tcp, _raop._tcp",
      "ports": [p("111 · rpcbind"), p("8123 · polipo", cat="web")]}, "Home Assistant", "server"),
    ("10.0.0.87", "5C:CF:7F:00:00:A7", "10.0.0.87",
     {"http_title": "Termostato - Main Menu", "http_server": "Tasmota/13.0.0 (ESP8266EX)",
      "ports": [p("80 · http", cat="web")]}, "Termostato", "iot"),
]


async def main():
    for ip, mac, name, info, want_name, want_type in CASES:
        dev = {"id": "x" + ip, "name": name, "ip": ip, "port": 80, "adapter": "generic", "scan_info": info, "last_mac": mac}
        res = await probe.probe_device(dev)
        typ = ha_data.infer_type(res)
        print(f"{ip:12} name={res['name']!r:28} type={typ:8} brand={res['brand']!r} ({res['brand_evidence']})")
        assert want_name.lower() in res["name"].lower(), (ip, res["name"], want_name)
        assert typ == want_type, (ip, typ, want_type)
        if ip == "10.0.0.100":
            assert res["brand"] != "Sony", res["brand"]

asyncio.run(main())

# Android phone: mDNS announces a random hostname, DHCP the real name ("Pixel-7").
from app.recognition import naming  # noqa: E402
assert naming.pick([("mdns", "Android_MGDZ1OUL"), ("dhcp", "Pixel-7")]) == ("Pixel-7", "dhcp")
assert naming.pick([("mdns", "Android_MGDZ1OUL")]) == ("Android_MGDZ1OUL", "weak")   # better than the IP
assert naming.pick([("mdns", "Galaxy-S23"), ("dhcp", "x1")])[1] == "mdns"           # real name: it stays
assert naming.is_better({"name": "Android_MGDZ1OUL", "ip": "1", "name_source": "weak"}, "dhcp")

# The phone is already saved with the random hostname: as soon as DHCP gives the real name it replaces it.
from app.scan import dhcp  # noqa: E402
dhcp.seen["0c:c4:13:00:00:b0"] = {"hostname": "Pixel-7"}
phone = {"id": "ph", "name": "Android_1MRKG1M7", "name_source": "mdns", "ip": "10.0.0.108", "port": 80, "adapter": "generic",
         "scan_info": {"mdns_name": "Android_1MRKG1M7"}, "last_mac": "0C:C4:13:00:00:B0"}
res = asyncio.run(probe.probe_device(phone))
assert res["name"] == "Pixel-7" and res["auto_name"][:2] == ("Pixel-7", "dhcp"), (res["name"], res["auto_name"])
assert naming.is_better({"name": "Android_1MRKG1M7", "ip": "x", "name_source": "mdns"}, "dhcp")
assert not naming.is_better({"name": "Android_1MRKG1M7", "ip": "x", "name_source": "user"}, "dhcp")  # chosen by hand
assert not naming.is_better({"name": "Mio telefono", "ip": "x", "name_source": "mdns"}, "dhcp")

# Fire TV Stick: the hostname is just "Android" (platform word, not a name): Amazon MAC + mDNS name
# amzn agree on the brand, the service says the type -> default name "brand + type".
fire = {"id": "ft", "name": "Android", "name_source": "dhcp", "ip": "10.0.0.103", "port": 80, "adapter": "generic",
        "scan_info": {"mdns_name": "amzn.dmgr:37F86A463D38E919EF206906B559C", "mdns_services": "_amzn-wplay._tcp",
                      "ports": [p("40027 · Amazon FireTV Stick", True)]}, "last_mac": "F8:54:B8:00:00:AB"}
res = asyncio.run(probe.probe_device(fire))
assert res["name"] == "Amazon streaming" and res["brand_evidence"] == "confirmed", (res["name"], res["brand_evidence"])
res = asyncio.run(probe.probe_device({**fire, "name_source": "user"}))
assert res["name"] == "Android"   # chosen by hand: never changed

# Zigbee/Matter gateway (Tasmota): a network bridge, not just any device -> Network devices.
gw = {"id": "gw", "name": "Tasmota_gateway_zigbee", "name_source": "dhcp", "ip": "10.0.0.101", "port": 80, "adapter": "generic",
      "scan_info": {"http_server": "Tasmota/13.0.0 (ESP8266EX)", "ports": [p("80 · http", cat="web")]}, "last_mac": "48:3F:DA:00:00:AE"}
res = asyncio.run(probe.probe_device(gw))
assert ha_data.infer_type(res) == "router", ha_data.type_scores(res)
# the operating system estimated by nmap is no longer a device datum
assert "os" not in res["extra"] and not hasattr(naming, "os_name")

# Home Assistant data (registry matched by MAC): name chosen by the user in HA, manufacturer, model,
# area and category from the integration; below the name chosen in Vedetta; technical names do not count.
from app.ha import ha_registry  # noqa: E402
CARDS = {}
ha_registry.lookup = lambda mac, ip=None: CARDS.get(str(mac or "").lower())


def probe_ha(name, source, mac, card, info=None):
    CARDS.clear()
    if card:
        CARDS[mac.lower()] = card
    dev = {"id": "h" + mac, "name": name, "name_source": source, "ip": "10.0.0.50", "port": 80, "adapter": "generic",
           "scan_info": info or {}, "last_mac": mac}
    return asyncio.run(probe.probe_device(dev))


strip = {"name": "Strip RGB", "name_by_user": True, "manufacturer": "Zengge", "model": "Controller RGB with MIC (0x08)",
         "area": "Cameretta", "domains": ["flux_led"], "entry_titles": ["Controller RGB with MIC 0000A1"], "entity_names": []}
res = probe_ha("10.0.0.50", None, "B4:E8:42:00:00:A1", strip)
assert res["name"] == "Strip RGB" and res["auto_name"][:2] == ("Strip RGB", "ha_user"), (res["name"], res["auto_name"])
assert res["brand"] == "Magic Home" and res["extra"]["ha_area"] == "Cameretta" and res["extra"]["ha_integration"] == "flux_led"
assert ha_data.infer_type(res) == "iot" and ha_data.icon_for(res) == "led-strip-variant", (ha_data.infer_type(res), ha_data.icon_for(res))
# HA technical name: the integration title ("Cancelletto") is used, never "shelly1-8CAA..."
sh = {"name": "shelly1-8CAAB50000A2", "name_by_user": False, "manufacturer": "Shelly", "model": "Shelly 1", "area": "Soggiorno",
      "domains": ["shelly"], "entry_titles": ["Cancelletto"], "entity_names": []}
res = probe_ha("10.0.0.50", None, "8C:AA:B5:00:00:A2", sh)
assert res["name"] == "Cancelletto" and res["auto_name"][:2] == ("Cancelletto", "ha"), (res["name"], res["auto_name"])
# the name changes in HA: the dashboard follows it (same weight, so the forced replacement is needed)
CARDS.clear(); CARDS["b4:e8:42:00:00:a1"] = {**strip, "name": "Strip LED camera"}
res = asyncio.run(probe.probe_device({"id": "x", "name": "Strip RGB", "name_source": "ha_user", "ip": "10.0.0.50", "port": 80,
                                      "adapter": "generic", "scan_info": {}, "last_mac": "B4:E8:42:00:00:A1"}))
assert res["name"] == "Strip LED camera" and res["auto_name"] == ("Strip LED camera", "ha_user", True), (res["name"], res["auto_name"])
# in HA the user removes the personal name: the integration name remains; the name chosen in Vedetta does not
CARDS["b4:e8:42:00:00:a1"] = {**strip, "name": "Controller RGB", "name_by_user": False}
res = asyncio.run(probe.probe_device({"id": "x", "name": "Strip RGB", "name_source": "ha_user", "ip": "10.0.0.50", "port": 80,
                                      "adapter": "generic", "scan_info": {}, "last_mac": "B4:E8:42:00:00:A1"}))
assert res["name"] == "Controller RGB" and res["auto_name"][1] == "ha", (res["name"], res["auto_name"])
assert asyncio.run(probe.probe_device({"id": "x", "name": "Mio", "name_source": "user", "ip": "10.0.0.50", "port": 80, "adapter": "generic",
                                       "scan_info": {}, "last_mac": "B4:E8:42:00:00:A1"}))["name"] == "Mio"
CARDS.clear()
# name chosen in Vedetta: never changed
res = probe_ha("Mio nome", "user", "B4:E8:42:00:00:A1", strip)
assert res["name"] == "Mio nome" and res["auto_name"] is None
# automatic name from a stronger source (mDNS 70) beats the default HA name (68), but not the one chosen by the user in HA (95)
res = probe_ha("Salotto", "mdns", "8C:AA:B5:00:00:A2", sh)
assert res["name"] == "Salotto"
res = probe_ha("Salotto", "mdns", "B4:E8:42:00:00:A1", strip)
assert res["name"] == "Strip RGB"
# the integration declares the category
cam = {"name": "Camera giardino", "name_by_user": True, "manufacturer": "IPCAM", "model": "C6F0SoZ3", "area": "Giardino",
       "domains": ["onvif"], "entry_titles": [], "entity_names": []}
res = probe_ha("10.0.0.50", None, "00:AD:11:00:00:B1", cam)
assert ha_data.infer_type(res) == "media" and ha_data.icon_for(res) == "cctv"
# Zigbee gateway with Tasmota integration: the platform (Tasmota) does not decide, it stays "network device"
zb = {"name": "Gateway Zigbee", "name_by_user": True, "manufacturer": "Tasmota", "model": "Sonoff ZbBridge", "area": "Corridoio",
      "domains": ["tasmota"], "entry_titles": [], "entity_names": []}
res = probe_ha("10.0.0.50", None, "48:3F:DA:00:00:AE", zb)
assert res["name"] == "Gateway Zigbee" and ha_data.infer_type(res) == "router", (res["name"], ha_data.type_scores(res))
# specific integration (Shelly gate called "Cancello"): stays smart-home
CARDS.clear()

# DNS server with no name (login page "Login", MAC of a VM): the role detected on the network gives the name
CARDS.clear()
saved = roles.roles_for
roles.roles_for = lambda ip: ["dns"] if ip == "10.0.0.2" else []
dns = {"id": "dns", "name": "10.0.0.2", "ip": "10.0.0.2", "port": 80, "adapter": "generic",
       "scan_info": {"http_title": "Login", "ports": [p("80 · http", cat="web")]}, "last_mac": "BC:24:11:00:00:A4"}
res = asyncio.run(probe.probe_device(dns))
assert res["name"] == "Server DNS", res["name"]
assert asyncio.run(probe.probe_device({**dns, "name": "AdGuard", "name_source": "user"}))["name"] == "AdGuard"
roles.roles_for = saved

# PlayStation 3 with webMAN: the page is titled like the software ("wMAN MOD 1.47.45"), not the name of the
# device; the declared DHCP class ("PS3") and the Sony MAC say what it is.
dhcp.seen["00:24:8d:00:00:b2"] = {"vendor_class": "PS3", "prl": "1,3,15,6"}
assert naming.title_name("wMAN MOD 1.47.45") is None and naming.title_name("Pi-hole") == "Pi-hole"
ps3 = {"id": "ps", "name": "wMAN MOD 1.47.45", "name_source": "web", "ip": "10.0.0.119", "port": 80, "adapter": "generic",
       "scan_info": {"http_title": "wMAN MOD 1.47.45", "ports": [p("21 · ftp", True), p("80 · http", cat="web"), p("9309 · unknown")]},
       "last_mac": "00:24:8D:00:00:B2"}
res = asyncio.run(probe.probe_device(ps3))
assert res["name"] == "Sony console" and ha_data.type_scores(res)["media"] >= 2 and ha_data.icon_for(res) == "gamepad-variant", (res["name"], ha_data.type_scores(res))

# iPhone with private address: no name from any source, only the brand (from the DHCP class): "brand + type"
dhcp.seen["42:4b:cd:00:00:a3"] = {"prl": "1,121,3,6,15,108,114,119,252"}
ip_phone = {"id": "ip", "name": "10.0.0.112", "ip": "10.0.0.112", "port": 80, "adapter": "generic", "scan_info": {}, "last_mac": "42:4B:CD:00:00:A3"}
res = asyncio.run(probe.probe_device(ip_phone))
assert res["brand"] == "Apple" and res["name"] == "Apple mobile", (res["brand"], res["name"], res["is_mobile"])
# the name built by the app does not count as a clue (it is not a phone "because it is called phone")
kinds_seen = {}
ha_data.type_scores(res, None, kinds_seen)
assert res["name_generated"] and "smartphone" not in kinds_seen, kinds_seen
# an iPad and an iPhone are indistinguishable from DHCP alone: the name must not say "phone"

# Certificate subject read in pure Python (non-standard TLS ports, e.g. 8006).
import shutil, ssl, subprocess, tempfile  # noqa: E402
from app.scan import scanner  # noqa: E402
if shutil.which("openssl"):
    d = tempfile.mkdtemp()
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", d + "/k.pem", "-out", d + "/c.pem",
                    "-days", "2", "-subj", "/CN=pve.local/O=Proxmox Virtual Environment"], capture_output=True, check=True)
    subject = scanner.cert_subject(ssl.PEM_cert_to_DER_cert(open(d + "/c.pem").read()))
    assert subject == "commonName=pve.local/organizationName=Proxmox Virtual Environment", subject
assert scanner.cert_subject(b"") is None
print("TUTTO OK")
