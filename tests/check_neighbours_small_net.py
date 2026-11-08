"""Issue #35: a device that does not answer broadcast ARP (an LG TV on Wi-Fi) but that the system has just seen answer (`ip neigh`, REACHABLE) is on the network.
On a normal network (up to a /24) the view of the ARP and the first search must count it too, as the large network already does; it costs no packet (the neighbour table is only read).
Checked with fake primitives: arp-scan finds A, the neighbour table has A (other vendor) and B; B must be added once, A must keep what arp-scan said, a failing read changes nothing.
    python tests/check_neighbours_small_net.py"""
import asyncio
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
try:
    import app.applog  # noqa: F401
except Exception:
    import logging
    stub = types.ModuleType("app.applog")
    stub.logger = logging.getLogger("dashboard")
    sys.modules["app.applog"] = stub

from app import arpview, netutil  # noqa: E402
from app.arpview import ArpView  # noqa: E402
from app.scan import pipeline, scanner  # noqa: E402
from app.networks import registry as _routes  # noqa: E402
_routes.ROUTE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "no-route-file")   # the fake network, not the routes of this computer

NET, OWN = "10.0.0.0/24", "10.0.0.2"
A = {"ip": "10.0.0.10", "mac": "AA:BB:CC:00:00:0A", "vendor": "Maker A"}
A_NEIGH = {"ip": "10.0.0.10", "mac": "AA:BB:CC:00:00:0A", "vendor": None}
B = {"ip": "10.0.0.11", "mac": "AA:BB:CC:00:00:0B", "vendor": None}
CALLS: list = []
NEIGH: dict = {"hosts": [A_NEIGH, B]}


async def fake_arp_scan(targets=None, timeout=0, interval_ms=None):
    CALLS.append(("arp_scan", tuple(targets or ())))
    return [dict(A)]


async def fake_neighbors(net=None):
    CALLS.append(("neighbors", net))
    return [dict(h) for h in NEIGH["hosts"]]


async def fake_network():
    return NET, OWN


scanner.arp_scan = fake_arp_scan
scanner.neighbors = fake_neighbors
netutil.get_local_network = fake_network    # the first search and arpview ask networks.registry.main(), which reads it
arpview.devices_config.load_devices = lambda: [{"ip": "10.0.0.10"}, {"ip": "10.0.0.11"}]


def by_ip(hosts) -> dict:
    out: dict = {}
    for h in hosts:
        assert h["ip"] not in out, "address listed twice: %r" % hosts
        out[h["ip"]] = h
    return out


async def main() -> None:
    view = ArpView(lambda blocks: None)
    # 1) whole sweep of a normal network: B (silent to broadcast ARP, seen by the system) is in the view, A keeps the vendor of arp-scan
    result, _ = await view._arp_small()
    got = by_ip(result.values())
    assert set(got) == {"10.0.0.10", "10.0.0.11"}, got
    assert got["10.0.0.10"]["vendor"] == "Maker A", got
    assert ("neighbors", NET) in CALLS, CALLS
    # 2) the checks between the sweeps (only the configured devices asked): B is still counted
    CALLS.clear()
    result, _ = await view._arp_small()
    assert CALLS[0][0] == "arp_scan" and CALLS[0][1], "expected the check of the configured devices, got %r" % CALLS
    assert set(by_ip(result.values())) == {"10.0.0.10", "10.0.0.11"}
    # 3) B no longer in the neighbour table (gone): after the next check it is not in the view any more
    NEIGH["hosts"] = [A_NEIGH]
    result, _ = await view._arp_small()
    assert set(by_ip(result.values())) == {"10.0.0.10"}, result
    # 4) the table cannot be read (scanner.neighbors returns []): the view is the one of arp-scan, nothing breaks
    NEIGH["hosts"] = []
    result, _ = await view._arp_small()
    assert set(by_ip(result.values())) == {"10.0.0.10"}
    # 5) the first search (the + of the interface): B is offered too, A once, the own computer still added
    NEIGH["hosts"] = [A_NEIGH, B]
    hosts = await pipeline.run_initial()
    got = by_ip(hosts)
    assert {"10.0.0.10", "10.0.0.11"} <= set(got), got
    # 6) never a packet more: the neighbour table is only read, arp-scan is asked as before (once per call)
    assert all(c[0] in ("arp_scan", "neighbors") for c in CALLS), CALLS


asyncio.run(main())
print("TUTTO OK")
