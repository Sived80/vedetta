"""A deep search must not erase what a device announced before (an iPhone asleep must not fall to "Other devices")."""
import asyncio
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.storage import devices_config
from app import i18n
from app.scan import pipeline, rescan  # noqa: E402

i18n.use("en")
tmp = Path(tempfile.mkdtemp())
devices_config.DEVICES_PATH = tmp / "devices.yaml"
devices_config.CONFIG_DIR = tmp
rescan.history = SimpleNamespace(save_scan=lambda *a, **k: None)      # no database in this test


async def _no_refresh(*a, **k):
    return None


# no network, no probe, no background port scan in this test
rescan.state = SimpleNamespace(refresh_device=_no_refresh, emit_alert=lambda *a, **k: None, _last_mac={})
rescan.schedule_full_ports = lambda device: None

devices_config.add_devices([{"ip": "10.0.0.7", "name": "iPhone", "adapter": "generic", "port": 80}])
did = devices_config.load_devices()[0]["id"]
BEFORE = {"mdns_name": "Phone-of-Test", "mdns_model": "iPhone15,2", "mdns_services": "_companion-link._tcp",
          "http_title": "Old page", "scanned_at": 1.0}


def run(result):
    devices_config.update_scan_info(did, dict(BEFORE))

    async def fake_deep(ip, batch, slow=False):
        return result
    pipeline.run_deep = fake_deep
    asyncio.run(rescan.rescan_device(devices_config.load_devices()[0], None))
    return devices_config.load_devices()[0]["scan_info"]


# 1) the phone answers nothing this time but the scan still produced something (slow-scan flag): all old clues stay
info = run({"slow_scan": True})
assert info["mdns_name"] == "Phone-of-Test" and info["mdns_model"] == "iPhone15,2", info
assert info["http_title"] == "Old page"                      # nothing answered at all: nothing contradicts it
assert info["scanned_at"] > 1.0                              # but the scan did happen

# 2) the host now shows an open port: announced clues stay, port-bound ones follow the new scan
info = run({"ports": [{"port": 22, "service": "ssh", "confirmed": True}]})
assert info["mdns_model"] == "iPhone15,2" and info["mdns_services"]
assert "http_title" not in info                              # the web page is gone, so is its title
assert info["ports"][0]["label"].startswith("22")

# 3) a new value always wins over the old one
info = run({"mdns_name": "New-name", "ports": [{"port": 22, "service": "ssh", "confirmed": True}]})
assert info["mdns_name"] == "New-name" and info["mdns_model"] == "iPhone15,2"
# 4) a clue read from a port is not erased by a read that did not happen: the web port is still open, the title was not read this time (the case of Home Assistant on 8123: the title brought the brand and the link)
BEFORE_WEB = {"http_title": "Home Assistant", "http_server": "x", "ssh_hostkey": "ssh-ed25519 AAAA", "snmp_descr": "linux", "scanned_at": 1.0,
              "ports": [{"label": "22 · ssh", "confirmed": True, "category": "infra", "web_ui": False}, {"label": "8123 · polipo", "confirmed": False, "category": "web", "web_ui": True}]}


def run_web(result):
    devices_config.update_scan_info(did, dict(BEFORE_WEB))

    async def fake_deep(ip, batch, slow=False):
        return result
    pipeline.run_deep = fake_deep
    asyncio.run(rescan.rescan_device(devices_config.load_devices()[0], None))
    return devices_config.load_devices()[0]["scan_info"]


info = run_web({"ports": [{"port": 22, "service": "ssh", "confirmed": True}, {"port": 8123, "service": "polipo", "confirmed": False}]})
assert info["http_title"] == "Home Assistant" and info["http_server"] == "x", info              # the web port is still open: the title stays
assert info["ssh_hostkey"] and info["snmp_descr"], info                                          # and the other ports are still open too
info = run_web({"ports": [{"port": 22, "service": "ssh", "confirmed": True}]})
assert "http_title" not in info and "http_server" not in info, info                              # the web port is gone: its title goes
assert info["ssh_hostkey"], info                                                                # port 22 is still there
info = run_web({"ports": [{"port": 80, "service": "http", "confirmed": True}]})
assert "http_title" not in info and "ssh_hostkey" not in info, info                              # another port answers, none of the old ones: nothing is kept
info = run_web({"ports": [{"port": 8123, "service": "polipo", "confirmed": False}], "http_title": "Home Assistant 2"})
assert info["http_title"] == "Home Assistant 2", info                                            # a new value always wins
# 5) the ports kept from the analysis (a card with no `scanned_at` yet) are not erased by a deep search that answers something but finds no port (a TV or a recorder that stalls under the
#    long scan: the analysis had seen its ports); once a deep search has read ports, an empty result is held ONCE (the device most probably did not answer: seen on 22 Oct with a camera and an ESPHome device while
#    the host disk was saturated) and taken as a real change the second time in a row (scan/rescan.py _hold_unanswered_ports; its own test is check_ports_unanswered)
ANALYSIS_PORTS = [{"label": "554 · rtsp", "confirmed": True, "category": "media"}, {"label": "80 · http", "confirmed": True, "category": "web", "web_ui": True, "web_scheme": "http"}]


def run_ports(before, result):
    devices_config.update_scan_info(did, dict(before))

    async def fake_deep(ip, batch, slow=False):
        return result
    pipeline.run_deep = fake_deep
    asyncio.run(rescan.rescan_device(devices_config.load_devices()[0], None))
    return devices_config.load_devices()[0]["scan_info"]


info = run_ports({"ports": ANALYSIS_PORTS, "http_title": "x"}, {"mdns_name": "Answered-but-no-ports"})
assert info["ports"] == ANALYSIS_PORTS and info["mdns_name"] == "Answered-but-no-ports" and info["scanned_at"] > 1.0, info
info = run_ports({"ports": ANALYSIS_PORTS, "scanned_at": 1.0}, {"mdns_name": "Answered-but-no-ports"})
assert info["ports"] == ANALYSIS_PORTS and info["ports_unseen"] == 1, info                          # a deep search had read them: the first empty answer is held and remembered
info = run_ports({"ports": ANALYSIS_PORTS, "scanned_at": 1.0, "ports_unseen": 1}, {"mdns_name": "Answered-but-no-ports"})
assert "ports" not in info and "ports_unseen" not in info, info                                  # the second one in a row is true: now none is open
info = run_ports({"ports": ANALYSIS_PORTS}, {"ports": [{"port": 22, "service": "ssh", "confirmed": True}]})
assert [p["label"][:2] for p in info["ports"]] == ["22"], info                                   # a deep search that finds ports replaces the list
print("TUTTO OK")
