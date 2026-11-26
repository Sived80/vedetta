"""An old twin card whose name came from a service, not from a person, takes the twin name (26/11, an installation upgraded from older
versions): Home Assistant's address on a VLAN announces only the mDNS service of an app that runs on it, and an old version saved that
instance name ("esphome-builder-<random>") as the card name with no origin. Such a name is the automatic name the deep search recorded
(scan_info: mDNS, UPnP, API, NetBIOS, ONVIF, web title), not one chosen by hand: the twin name replaces it. A name with no origin that the
deep search never saw stays, as before (presumed chosen by hand).
    python tools/run_test.py check_twin_over_service_name.py"""
import os
import sys
import tempfile

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.storage import devices_config  # noqa: E402

failed = 0


def check(cond, msg):
    global failed
    print(("ok: " if cond else "FAILED: ") + msg)
    failed += 0 if cond else 1


def card(ip):
    return {d["ip"]: d for d in devices_config.load_devices()}[ip]


def with_scan(ip, **scan):
    def change(d):
        d["scan_info"] = {**(d.get("scan_info") or {}), **scan}
    devices_config._edit_card(card(ip)["id"], change)


TWIN = "Home Assistant (VLAN 20)"

# 1) the name an old version took from an app's mDNS service, saved with no origin
devices_config.add_devices([{"ip": "192.0.2.100", "name": "esphome-builder-x7k2qmwp"}])
with_scan("192.0.2.100", mdns_name="esphome-builder-x7k2qmwp", mdns_services="_esphomebuilder._tcp", http_title="Home Assistant")
check("name_source" not in card("192.0.2.100"), "the old card has no origin for its name")
check(devices_config.set_twin_name(card("192.0.2.100")["id"], TWIN), "the twin name replaces a name the deep search heard from a service")
check(card("192.0.2.100")["name"] == TWIN and card("192.0.2.100").get("name_source") == "twin", "the card is now named as a twin")

# 2) the same for a web title or a UPnP name kept with no origin
devices_config.add_devices([{"ip": "192.0.2.101", "name": "Router Login"}])
with_scan("192.0.2.101", http_title="Router Login")
check(devices_config.set_twin_name(card("192.0.2.101")["id"], TWIN), "a name that is the web title is automatic too")

# 3) a name with no origin the deep search never saw: chosen by hand, it stays
devices_config.add_devices([{"ip": "192.0.2.102", "name": "Cantina"}])
with_scan("192.0.2.102", mdns_name="esphome-builder-q3zt8nvh")
check(not devices_config.set_twin_name(card("192.0.2.102")["id"], TWIN), "a hand-written name stays")
check(card("192.0.2.102")["name"] == "Cantina", "and is not touched")

if failed:
    print("%d FAILED" % failed)
    sys.exit(1)
print("ALL OK")
