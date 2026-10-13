"""When the deep search of a slow device schedules the full port scan in the background (rescan._apply_name_and_refresh): only for a slow device, and only when the last full scan is older than
a week or the services were never read. The mutation «services never read no longer counts» used to survive every test of the project."""
import asyncio
import os
import sys
import tempfile
from types import SimpleNamespace

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import rescan  # noqa: E402

NOW = 10_000_000.0
scheduled: list = []


async def refresh(device_id, force=False):
    return None


rescan.state = SimpleNamespace(refresh_device=refresh, emit_alert=lambda *a, **k: None, _last_mac={})
rescan.schedule_full_ports = lambda device: scheduled.append(device["id"])


def runs(slow: bool, previous: dict) -> bool:
    del scheduled[:]
    device = {"id": "d1", "ip": "10.0.0.9", "name": "x"}
    asyncio.run(rescan._apply_name_and_refresh({}, None, "10.0.0.9", 1.0, device, None, {"slow_scan": slow}, NOW, previous))
    return bool(scheduled)


WEEK = rescan.FULL_PORTS_EVERY_S
assert not runs(False, {}), "a device that is not slow never gets the background scan"
assert not runs(False, {"full_ports_at": 0}), "not slow, however old the last scan"
assert runs(True, {}), "slow, never scanned in full"
assert runs(True, {"full_ports_at": NOW - WEEK - 1, "services_at": NOW - 5}), "slow, the full scan is older than a week"
assert not runs(True, {"full_ports_at": NOW - WEEK + 60, "services_at": NOW - 5}), "slow, scanned in full less than a week ago and the services were read"
assert runs(True, {"full_ports_at": NOW - 60}), "slow, scanned recently but the services were never read"
print("TUTTO OK")
