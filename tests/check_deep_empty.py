"""A deep search that finds nothing must not leave the device "never analysed" forever."""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.storage import devices_config
from app.ha import ha_data
from app import i18n, maintenance
from app.scan import pipeline, rescan  # noqa: E402

i18n.use("en")
tmp = Path(tempfile.mkdtemp())
devices_config.DEVICES_PATH = tmp / "devices.yaml"
devices_config.CONFIG_DIR = tmp
devices_config.add_devices([{"ip": "10.0.0.8", "name": "Phone", "adapter": "generic", "port": 80}])
dev = devices_config.load_devices()[0]
devices_config.update_scan_info(dev["id"], {"mdns_name": "kept-name"})   # data from an older, useful scan
dev = devices_config.load_devices()[0]
assert "scanned_at" not in dev["scan_info"] and maintenance.last_deep_attempt(dev) == 0


async def silent_deep(ip, batch, slow=False):
    return {}                                                          # host answers nothing useful


pipeline.run_deep = silent_deep
asyncio.run(rescan.rescan_device(dev, None))

after = devices_config.load_devices()[0]
info = after["scan_info"]
assert info.get("deep_empty_at"), info                                  # the attempt is remembered
assert "scanned_at" not in info                                         # ...without claiming ports were read
assert info.get("mdns_name") == "kept-name"                             # older data kept
assert maintenance.last_deep_attempt(after) == info["deep_empty_at"]    # the night does not retry it every day

compact = ha_data.compact_device({"id": after["id"], "ip": "10.0.0.8", "name": "Phone", "extra": {}, "scanned_ports": [],
                                  "deep_empty_at": info["deep_empty_at"]}, after)
assert compact["deep_empty_at"] == info["deep_empty_at"] and not compact["scanned_at"]
print("TUTTO OK")
