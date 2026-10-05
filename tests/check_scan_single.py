"""Two simultaneous quick-search requests share a single scan."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import main  # noqa: E402

calls = {"n": 0}


async def fake_run_initial():
    calls["n"] += 1
    await asyncio.sleep(0.3)
    return [{"ip": "10.9.9.9", "mac": "AA:BB:CC:00:00:01", "vendor": None, "hostname": "x"}]


async def fake_net():
    return ("10.9.9.0/24", "10.9.9.1")


main.pipeline.run_initial = fake_run_initial
main.get_local_network = fake_net
main.devices_config.load_devices = lambda: []
main.newdevices.sync_present = lambda macs: None
main.newdevices.list_new = lambda: []
main.state.set_new_devices = lambda x: None
main.blocklist.matches = lambda **k: False


async def go():
    a, b = await asyncio.gather(main.api_scan_quick(), main.api_scan_quick())
    assert calls["n"] == 1, f"attese 1 scansione, avviate {calls['n']}"
    assert a.body == b.body and b"10.9.9.9" in a.body
    await main.api_scan_quick()  # after it ends a new one starts
    assert calls["n"] == 2, calls
    assert main.state._search_running == 0, main.state._search_running


asyncio.run(go())
print("TUTTO OK")
