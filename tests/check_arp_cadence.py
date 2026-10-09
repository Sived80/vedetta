"""On a normal network (up to a /24) the whole network is asked at most every FULL_SWEEP_S; the checks between ask only the configured devices,
and every ARP request is paced (arp-scan --interval). The view of the ARP stays whole: what the last sweep found is kept, updated by the
devices asked since. A refresh asked by hand sweeps the whole network again."""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import netutil  # noqa: E402
from app import state as state_mod  # noqa: E402
from app.scan import scanner  # noqa: E402
from app.storage import devices_config  # noqa: E402
from app.storage.history import History  # noqa: E402

tmp = Path(tempfile.mkdtemp())
state_mod.history = History(tmp / "vedetta.db")
calls = []
answers = {"192.168.1.10": "aa:bb:cc:00:00:10", "192.168.1.11": "aa:bb:cc:00:00:11", "192.168.1.50": "aa:bb:cc:00:00:50"}   # .50: a device nobody configured


async def fake_net():
    return "192.168.1.0/24", "192.168.1.5"


async def fake_arp(targets=None, timeout=0, interval_ms=None):
    calls.append((list(targets) if targets else None, interval_ms))
    asked = targets if targets else list(answers)
    return [{"ip": ip, "mac": answers[ip].upper(), "vendor": None} for ip in asked if ip in answers]


netutil.get_local_network = fake_net
scanner.arp_scan = fake_arp
configured = [{"id": "a", "ip": "192.168.1.10"}, {"id": "b", "ip": "192.168.1.11"}, {"id": "c", "ip": "192.168.1.12"}]
devices_config.load_devices = lambda: list(configured)


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


st = state_mod.DeviceState()
# 1) the first check sweeps the whole network, paced
view = run(st._arp_by_ip(0))
assert calls[-1] == (None, state_mod.SWEEP_INTERVAL_MS), calls[-1]
assert set(view) == set(answers), view
# 2) the checks that follow ask only the configured devices (3 addresses, not the 254 of the network), still paced
for _ in range(4):
    view = run(st._arp_by_ip(0))
    assert calls[-1] == (["192.168.1.10", "192.168.1.11", "192.168.1.12"], state_mod.SWEEP_INTERVAL_MS), calls[-1]
assert [c[0] for c in calls].count(None) == 1, "one sweep only"
assert "192.168.1.50" in view, "what the last sweep found is kept: a device nobody configured does not vanish from the view between sweeps"
# 3) a configured device that stops answering leaves the view at once; one that comes back returns
del answers["192.168.1.11"]
view = run(st._arp_by_ip(0))
assert "192.168.1.11" not in view and "192.168.1.10" in view and "192.168.1.50" in view
answers["192.168.1.11"] = "aa:bb:cc:00:00:11"
assert "192.168.1.11" in run(st._arp_by_ip(0))
# 4) after FULL_SWEEP_S the whole network is asked again, and what the sweep does not find is gone
del answers["192.168.1.50"]
st._last_full -= state_mod.FULL_SWEEP_S + 1
view = run(st._arp_by_ip(0))
assert calls[-1][0] is None and "192.168.1.50" not in view and set(view) == {"192.168.1.10", "192.168.1.11"}, (calls[-1], view)
# 5) a refresh asked by hand sweeps the whole network at the next check
run(st._arp_by_ip(0))
assert calls[-1][0] is not None
st.trigger(force=True)
run(st._arp_by_ip(0))
assert calls[-1][0] is None and st._last_full is not None
# 6) with nothing configured there is nothing to ask in between: the whole network every time (as before)
configured.clear()
run(st._arp_by_ip(0))
run(st._arp_by_ip(0))
assert calls[-1][0] is None and calls[-2][0] is None
# 7) the request count of a check: configured devices only, never the whole network
configured.extend({"id": str(i), "ip": f"192.168.1.{100 + i}"} for i in range(46))
st2 = state_mod.DeviceState()
run(st2._arp_by_ip(0))
run(st2._arp_by_ip(0))
assert len(calls[-1][0]) == 46 and st2._asked == 46, "46 addresses a check instead of 254"
# 8) the scanner puts the pause between packets on the command line, and only when asked to
made = []
real_exec = asyncio.create_subprocess_exec


class P:
    returncode = 0

    async def communicate(self, input=None):
        return b"", b""


async def fake_exec(*args, **kw):
    made.append(args)
    return P()


asyncio.create_subprocess_exec = fake_exec
try:
    import importlib
    importlib.reload(scanner)
    run(scanner.arp_scan(interval_ms=20))
    run(scanner.arp_scan(["10.0.0.1"]))
    run(scanner.arp_scan())
finally:
    asyncio.create_subprocess_exec = real_exec
assert "--interval=20" in made[0] and "--interval=20" not in made[1] and not any(a.startswith("--interval") for a in made[2]), made
print("TUTTO OK")
