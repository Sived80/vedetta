"""Brand and type chosen by hand: they win over every scan and stay until switched back to automatic."""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.storage import devices_config
from app.ha import ha_data
from app import i18n
from app.scan import probe
from app.recognition import roles  # noqa: E402

i18n.use("it")
tmp = Path(tempfile.mkdtemp())
devices_config.DEVICES_PATH = tmp / "devices.yaml"
devices_config.CONFIG_DIR = tmp
devices_config.add_devices([{"ip": "10.0.0.9", "name": "10.0.0.9", "adapter": "generic", "port": 80}])
did = devices_config.load_devices()[0]["id"]

assert devices_config.set_override(did, "type_user", "printer")["type_user"] == "printer"
assert devices_config.set_override(did, "brand_user", "Acme")["brand_user"] == "Acme"
assert devices_config.set_override(did, "nome", "x") is None  # only the expected fields
cfg = devices_config.load_devices()[0]
assert cfg["type_user"] == "printer" and cfg["brand_user"] == "Acme"

dev = {"id": did, "ip": "10.0.0.9", "name": "Apparecchio", "extra": {}, "scanned_ports": [{"label": "554 · rtsp"}]}
roles.roles_for = lambda ip: []
roles.upnp_types = lambda ip: []
assert ha_data.effective_type(dev, cfg) == "printer"          # by hand, even if the ports say otherwise
assert ha_data.compact_device(dev, cfg)["type_user"] == "printer"
probe.ADAPTERS = {}
res = asyncio.run(probe.probe_device({**cfg, "name": "10.0.0.9"}))
assert res["brand"] == "Acme" and res["brand_source"] == "user" and res["brand_evidence"] == "confirmed", res["brand"]
# automatic: the fields disappear and the score is back
devices_config.set_override(did, "type_user", None)
devices_config.set_override(did, "brand_user", None)
cfg = devices_config.load_devices()[0]
assert "type_user" not in cfg and "brand_user" not in cfg
assert ha_data.effective_type(dev, cfg) != "printer"
print("TUTTO OK")
