"""A deep search must not erase what a device announced before (an iPhone asleep must not fall to "Other devices")."""
import asyncio
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import devices_config, i18n, pipeline, rescan  # noqa: E402

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
print("TUTTO OK")
