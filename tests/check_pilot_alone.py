"""The pilot test (1000 ports, judged against PILOT_MAX_S) must be measured with nothing else heavy running: under load a healthy device took 6-16 s
instead of 0.5-3 s and was wrongly judged slow (so it lost its high ports). Rules checked here with a fake nmap: only one pilot at a time, no heavy
nmap while a pilot runs, a heavy nmap already running is waited for, and the permits are always given back (also when the pilot is cancelled)."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import scan_nmap as nm  # noqa: E402

XML = '<?xml version="1.0"?><nmaprun><runstats><finished elapsed="1.0"/></runstats></nmaprun>'
HEAVY = nm._NMAP_SEMAPHORE._value

state = {"running": 0, "peak": 0, "heavy_free_during": []}


async def fake_run_nmap(args, semaphore=None):
    state["running"] += 1
    state["peak"] = max(state["peak"], state["running"])
    state["heavy_free_during"].append(nm._NMAP_SEMAPHORE._value)
    await asyncio.sleep(0.02)
    state["running"] -= 1
    return XML


nm._run_nmap = fake_run_nmap


async def main():
    # 1. many pilots together: one at a time, and the heavy slots are all taken while each one measures
    await asyncio.gather(*(nm.pilot("10.0.0.%d" % i) for i in range(1, 6)))
    assert state["peak"] == 1, "pilots must not overlap, peak=%d" % state["peak"]
    assert state["heavy_free_during"] == [0] * 5, "no heavy nmap may run during a pilot: %r" % state["heavy_free_during"]
    assert nm._NMAP_SEMAPHORE._value == HEAVY, "heavy slots given back"

    # 2. a heavy nmap already running is waited for, not interrupted
    await nm._NMAP_SEMAPHORE.acquire()
    started = []
    task = asyncio.ensure_future(nm.pilot("10.0.0.9"))
    task.add_done_callback(lambda _: started.append("done"))
    await asyncio.sleep(0.1)
    assert not started, "the pilot must wait while a heavy nmap holds a slot"
    nm._NMAP_SEMAPHORE.release()
    await task
    assert nm._NMAP_SEMAPHORE._value == HEAVY

    # 3. a cancelled pilot gives everything back (also while it waits for the second slot)
    await nm._NMAP_SEMAPHORE.acquire()
    task = asyncio.ensure_future(nm.pilot("10.0.0.10"))
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    nm._NMAP_SEMAPHORE.release()
    assert nm._NMAP_SEMAPHORE._value == HEAVY, "slots leaked by a cancelled pilot: %d" % nm._NMAP_SEMAPHORE._value
    assert not nm._PILOT_LOCK.locked(), "pilot lock leaked"
    await asyncio.wait_for(nm.pilot("10.0.0.11"), 2)   # and the next pilot still runs


asyncio.new_event_loop().run_until_complete(main())
print("OK check_pilot_alone")
