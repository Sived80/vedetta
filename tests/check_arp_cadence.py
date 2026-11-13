"""1.0 step P8: on a normal network (up to a /24) the first check asks the whole network (the starting picture, as before); the checks that
follow ask one slice of the network a cycle, in turn (arpplan, cycle_s), plus the configured devices; every slice is asked within
arpplan.ROUND_S. Every ARP request is paced (arp-scan --interval). What a slice told is kept until the slice is asked again. A refresh asked
by hand asks the whole network again."""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import arpview, netutil  # noqa: E402
from app import state as state_mod  # noqa: E402
from app.scan import scanner  # noqa: E402
from app.storage import devices_config  # noqa: E402
from app.storage.history import History  # noqa: E402
from app.networks import registry as _routes  # noqa: E402
_routes.ROUTE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "no-route-file")   # the fake network, not the routes of this computer

tmp = Path(tempfile.mkdtemp())
state_mod.history = arpview.history = History(tmp / "vedetta.db")
calls = []
answers = {"192.168.1.10": "aa:bb:cc:00:00:10", "192.168.1.11": "aa:bb:cc:00:00:11", "192.168.1.50": "aa:bb:cc:00:00:50"}   # .50: a device nobody configured


async def fake_net():
    return "192.168.1.0/24", "192.168.1.5"


def _expand(targets):
    import ipaddress
    out = []
    for t in targets:
        out += [str(a) for a in ipaddress.ip_network(t, strict=False)] if "/" in t else [t]
    return out


async def fake_arp(targets=None, timeout=0, interval_ms=None):
    calls.append((list(targets) if targets else None, interval_ms))
    asked = _expand(targets) if targets else list(answers)
    return [{"ip": ip, "mac": answers[ip].upper(), "vendor": None} for ip in asked if ip in answers]


netutil.get_local_network = fake_net
scanner.arp_scan = fake_arp
configured = [{"id": "a", "ip": "192.168.1.10"}, {"id": "b", "ip": "192.168.1.11"}, {"id": "c", "ip": "192.168.1.12"}]
devices_config.load_devices = lambda: list(configured)


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


st = state_mod.DeviceState()
# 1) the first check asks the whole network, paced (the starting picture)
view = run(st._arp_by_ip(0))
assert calls[-1] == (None, arpview.SWEEP_INTERVAL_MS), calls[-1]
assert set(view) == set(answers), view
# 2) then one slice a cycle (32 addresses with the 30 s cycle), plus the configured devices outside it, still paced
view = run(st._arp_by_ip(0))
assert calls[-1] == (["192.168.1.0/27"], arpview.SWEEP_INTERVAL_MS), calls[-1]          # .10 .11 .12 are inside the first slice
view = run(st._arp_by_ip(0))
assert calls[-1] == (["192.168.1.32/27", "192.168.1.10", "192.168.1.11", "192.168.1.12"], arpview.SWEEP_INTERVAL_MS), calls[-1]
assert "192.168.1.50" in view, "the device nobody configured, found by its slice, stays in the view"
# 3) a configured device that stops answering leaves the view at the next check; one that comes back returns
del answers["192.168.1.11"]
view = run(st._arp_by_ip(0))
assert "192.168.1.11" not in view and "192.168.1.10" in view and "192.168.1.50" in view, view
answers["192.168.1.11"] = "aa:bb:cc:00:00:11"
assert "192.168.1.11" in run(st._arp_by_ip(0))
# 4) every slice is asked within a round: 8 slices of 32 addresses
slices = set()
for _ in range(8):
    run(st._arp_by_ip(0))
    slices.add(calls[-1][0][0])
assert slices == {"192.168.1.%d/27" % (32 * i) for i in range(8)}, slices
# 5) a device that leaves disappears when its slice is asked again
del answers["192.168.1.50"]
for _ in range(8):
    view = run(st._arp_by_ip(0))
assert "192.168.1.50" not in view, view
# 6) a refresh asked by hand asks the whole network at the next check, then the slices again
st.trigger(force=True)
run(st._arp_by_ip(0))
assert calls[-1][0] is None and st._view.last_full is not None
run(st._arp_by_ip(0))
assert calls[-1][0] is not None and calls[-1][0][0].endswith("/27"), calls[-1]
# 7) the request count of a check: one slice and the configured devices outside it, never the whole network
configured.extend({"id": str(i), "ip": f"192.168.1.{100 + i}"} for i in range(46))
st2 = state_mod.DeviceState()
run(st2._arp_by_ip(0))
run(st2._arp_by_ip(0))
assert st2._view.asked <= 32 + 49 and calls[-1][0][0].endswith("/27") and calls[-1][0] is not None, (st2._view.asked, calls[-1])   # the history is shared: the turn of the slices goes on
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
