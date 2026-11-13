"""ARP only on the network of the interface (K10, G0-13 and G0-15 of the study of the networks).

A card whose address is not in the network the host is on (a device of a routed VLAN added by hand, a card left from the network of before)
is never asked by ARP: with proxy ARP on the router, the router answers for it with its own MAC, and the card would take the router's MAC and
look present even when it is off. Here a fake arp-scan answers with the router's MAC for any address outside the network: whatever a cycle
asks (since 1.0 step P8 one slice of the network and its configured devices) stays inside the network, and the view of the ARP holds no
address outside it.
Invented private and documentation addresses only.
    python tests/check_no_arp_for_foreign_ips.py"""
import asyncio
import ipaddress
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
NET, OWN = "192.168.50.0/24", "192.168.50.7"
INSIDE = {"192.168.50.10": "AA:BB:CC:00:00:10"}
ROUTER_MAC = "AA:BB:CC:00:00:01"
ROUTED, OLD = "192.168.60.20", "198.51.100.9"        # a device of a routed VLAN, a card left from another network
ASKED: list = []


def _inside(target) -> bool:
    return ipaddress.ip_network(target, strict=False).subnet_of(ipaddress.ip_network(NET))


async def fake_net():
    return NET, OWN


async def fake_arp(targets=None, timeout=0, interval_ms=None):
    ASKED.append(list(targets) if targets else None)
    if not targets:
        return [{"ip": ip, "mac": mac, "vendor": None} for ip, mac in INSIDE.items()]
    asked = [str(a) for tg in targets for a in (ipaddress.ip_network(tg, strict=False) if "/" in tg else [tg])]
    return [{"ip": ip, "mac": INSIDE.get(ip, ROUTER_MAC), "vendor": None} for ip in asked if ip in INSIDE or not _inside(ip)]   # proxy ARP: the router answers outside


async def no_neighbours(net=None):
    return []


netutil.get_local_network = fake_net
scanner.arp_scan, scanner.neighbors = fake_arp, no_neighbours
devices_config.load_devices = lambda: [{"id": "a", "ip": "192.168.50.10"}, {"id": "b", "ip": ROUTED}, {"id": "c", "ip": OLD}]


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


st = state_mod.DeviceState()
view = run(st._arp_by_ip(0))                         # the first check sweeps the network
assert ASKED[-1] is None, ASKED
for _ in range(3):                                   # the checks that follow ask a slice of the network and its configured devices
    view = run(st._arp_by_ip(0))
    assert ASKED[-1] and all(_inside(a) for a in ASKED[-1]), ("only the network is asked", ASKED[-1])
    assert ROUTED not in view and OLD not in view, ("no address outside the network in the view of the ARP", sorted(view))
    assert view["192.168.50.10"]["mac"] == "AA:BB:CC:00:00:10"

# no configured device in the network: the checks between sweeps ask nothing rather than the cards of other networks
devices_config.load_devices = lambda: [{"id": "b", "ip": ROUTED}, {"id": "c", "ip": OLD}]
ASKED.clear()
st = state_mod.DeviceState()
for _ in range(4):
    run(st._arp_by_ip(0))
assert all(ROUTED not in (a or []) and OLD not in (a or []) for a in ASKED), ASKED
assert ASKED[0] is None and all(len(a) == 1 and a[0].endswith("/27") and _inside(a[0]) for a in ASKED[1:]),     ("one sweep, then one slice of the network a cycle: never the whole network at every check (simulator S30b, 08/11)", ASKED)
print("check_no_arp_for_foreign_ips: ok")
