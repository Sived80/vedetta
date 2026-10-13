"""«Don't touch» is checked where the work actually starts, not only where it is planned. Found by the global review: the background scan of all ports waits for its turn (up to 900 s) and was not
asked again whether the device may be touched; and the batch of the deep search (mDNS reverse names: a unicast query to every address) was prepared for ALL the addresses, the ones that must not be
touched included. Rule: never risk commanding a device."""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import maintenance  # noqa: E402
from app.routes import device_routes  # noqa: E402
from app.scan import pipeline, rescan, rescan_background, touch_policy as tp  # noqa: E402
from app.storage import devices_config as dc  # noqa: E402

tmp = Path(tempfile.mkdtemp())
dc.CONFIG_DIR = tmp
dc.DEVICES_PATH = tmp / "devices.yaml"
run = lambda c: asyncio.new_event_loop().run_until_complete(c)   # noqa: E731

WEB = {"label": "80 · http", "confirmed": True}
PRINT = {"label": "9100 · jetdirect", "confirmed": False}
cards = [{"id": "a", "ip": "10.0.0.1", "scan_info": {"ports": [WEB]}}, {"id": "b", "ip": "10.0.0.2", "scan_info": {"ports": [PRINT]}},
         {"id": "c", "ip": "10.0.0.3", "no_touch": "on", "scan_info": {}}, {"id": "d", "ip": "10.0.0.4", "scan_info": {"slow_scan": True}}]
assert [d["id"] for d in tp.touchable(cards)] == ["a", "d"], "the ones that must not be touched are left out; a slow (calm) one stays"

# 1) the batch of the deep search gets only the addresses that may be touched
seen: list = []


async def stub_batch(profile, ips, steps=None):
    seen.append(list(ips))
    return pipeline.Batch(steps=[])


real_batch, real_rescan = pipeline.prepare_batch, maintenance.rescan_device
pipeline.prepare_batch = stub_batch


async def stub_rescan(device, batch):
    return {}


maintenance.rescan_device = stub_rescan
try:
    run(maintenance._rescan_stale(cards))
    run(device_routes._prepare_batch_or_release(cards))
finally:
    pipeline.prepare_batch, maintenance.rescan_device = real_batch, real_rescan
assert seen == [["10.0.0.1", "10.0.0.4"], ["10.0.0.1", "10.0.0.4"]], seen

# 2) the background scan of all ports checks again when its turn comes: the user may have said «don't touch» while it waited
dc.DEVICES_PATH.write_text("devices:\n- {id: a, ip: 10.0.0.1, port: 80, adapter: generic, no_touch: 'on'}\n- {id: b, ip: 10.0.0.2, port: 80, adapter: generic}\n", encoding="utf-8")
ran: list = []


async def stub_nmap(ip, args):
    ran.append(ip)
    return []


async def stub_refresh(*a, **k):
    return None


real_bg, real_refresh = rescan_background._background_nmap, rescan_background.state.refresh_device
rescan_background._background_nmap, rescan_background.state.refresh_device = stub_nmap, stub_refresh
try:
    run(rescan_background._scan_all_ports("a", "10.0.0.1"))      # became «don't touch» while it waited
    assert ran == [], "nmap ran against a device that must not be touched: %s" % ran
    run(rescan_background._scan_all_ports("b", "10.0.0.2"))
    assert ran == ["10.0.0.2"], ran
finally:
    rescan_background._background_nmap, rescan_background.state.refresh_device = real_bg, real_refresh
print("TUTTO OK")
