"""The one guard of the networks (networks/scope.py), against the guard of today.
1) differential: with the main network alone, Scope.allowed gives EXACTLY what netutil.filter_local_ips gives (the real function, with a fake `ip addr`), on 3000 addresses
   with a fixed seed, for several sizes of network (/16, /22, /24, /27); 2) only confirmed networks count, excluded ranges never; 3) a value that is not an IPv4 address
   belongs to no network and raises nothing; 4) metamorphic: the order of the networks does not matter, the order of the addresses is kept; 5) empty world.
Invented private addresses only.
    python tests/check_networks_scope.py"""
import asyncio
import ipaddress
import os
import random
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import netutil  # noqa: E402
from app.networks.model import Network, validate  # noqa: E402
from app.networks.scope import Scope  # noqa: E402


class FakeProc:
    def __init__(self, text: str):
        self.text = text

    async def communicate(self):
        return self.text.encode(), b""


def host_says(address: str):
    async def fake(*args, **kwargs):
        return FakeProc("3: lan9    inet %s brd 0.0.0.0 scope global lan9\n" % address)
    return fake


def main_network(cidr: str) -> Network:
    """The main network as the host gives it: never checked by validate (it is what it is)."""
    return Network("main", ipaddress.ip_network(cidr), frozenset({"direct"}), "full", "confirmed")


netutil.lan_iface = lambda: "lan9"
rng = random.Random(20261107)


def addresses_around(net: ipaddress.IPv4Network, n: int) -> list:
    """Half near the network (inside, on its edges, just outside), half anywhere."""
    lo, size = int(net.network_address), net.num_addresses
    out = []
    for _ in range(n):
        x = lo - 300 + rng.randrange(size + 600) if rng.random() < 0.5 else rng.randrange(1 << 32)
        out.append(str(ipaddress.IPv4Address(x % (1 << 32))))
    return out + [str(net.network_address), str(net.broadcast_address)]


# 1) differential
for own in ("10.20.2.50/16", "10.20.2.50/22", "192.168.50.7/24", "192.168.50.70/27"):
    netutil.asyncio.create_subprocess_exec = host_says(own)
    cidr = str(ipaddress.ip_interface(own).network)
    sample = addresses_around(ipaddress.ip_network(cidr), 3000)
    old = asyncio.run(netutil.filter_local_ips(sample))
    new = Scope((main_network(cidr),)).allowed(sample)
    assert new == old, (own, len(new), len(old))
    assert 0 < len(new) < len(sample), own

# 2) confirmed only, excluded ranges never
MAIN = main_network("192.168.50.0/24")
iot = validate({"id": "iot", "cidr": "192.168.60.0/24", "via": ["routed"], "state": "confirmed", "exclude": ["192.168.60.200-192.168.60.220"]}, [MAIN])
media = validate({"id": "media", "cidr": "192.168.70.0/24", "via": ["routed"], "state": "paused"}, [MAIN, iot])
guests = validate({"id": "guests", "cidr": "192.168.80.0/24", "via": ["routed"]}, [MAIN, iot, media])      # proposed: nobody confirmed it
scope = Scope((MAIN, iot, media, guests))
assert scope.network_of("192.168.50.9") is MAIN and scope.network_of("192.168.60.5") is iot
assert scope.network_of("192.168.60.199") is iot and scope.network_of("192.168.60.200") is None and scope.network_of("192.168.60.220") is None and scope.network_of("192.168.60.221") is iot
assert scope.network_of("192.168.70.5") is None, "paused"
assert scope.network_of("192.168.80.5") is None, "proposed"
assert scope.network_of("192.168.61.5") is None

# 3) values that are not addresses
inside_as_number = int(ipaddress.IPv4Address("192.168.60.5"))      # ipaddress would read a number or 4 bytes as an address: only text counts
for bad in ("", "a.b.c.d", "192.168.60.5 ", "192.168.60.5/24", "1.2.3", "192.168.060.5", "::1", None, 7, inside_as_number, bytes((192, 168, 60, 5)), b"192.168.60.5", ["192.168.60.5"]):
    assert scope.network_of(bad) is None, bad
assert scope.allowed(["192.168.60.5", None, "x", "192.168.50.1"]) == ["192.168.60.5", "192.168.50.1"]

# 4) metamorphic
sample = ["192.168.%d.%d" % (rng.choice([50, 60, 70, 80, 51]), rng.randrange(256)) for _ in range(3000)]
assert Scope((guests, media, iot, MAIN)).allowed(sample) == scope.allowed(sample)
assert scope.allowed(list(reversed(sample))) == list(reversed(scope.allowed(sample)))
truth = [ip for ip in sample if ip.startswith("192.168.50.") or (ip.startswith("192.168.60.") and not 200 <= int(ip.rsplit(".", 1)[1]) <= 220)]
assert scope.allowed(sample) == truth, "against a truth written with text only"

# 5) empty world
assert Scope(()).allowed(sample) == [] and Scope(()).network_of("192.168.50.1") is None

print("check_networks_scope: ok")
