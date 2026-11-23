"""The local network when Home Assistant's own address is a host address (/32 or /31): seen on a static address set with a /32 mask and a
gateway reached "on link". The network is not the address alone (only HA, nothing else found, and a /24 added by hand "overlaps" it): it is
the link route of the interface that holds the address or, without one, the /24 around the address. A normal prefix is kept as it is.
Fake `ip addr` and `ip route` outputs; documentation and private placeholder addresses."""
import asyncio
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import netutil  # noqa: E402


class FakeProc:
    def __init__(self, text: str):
        self.text = text

    async def communicate(self):
        return self.text.encode(), b""


asked = []


def host(addr: str, route: str):
    async def fake(*args, **kwargs):
        asked.append("route" if "route" in args else "addr")
        return FakeProc(route if "route" in args else addr)
    return fake


def read(addr: str, route: str = ""):
    asked.clear()
    netutil.asyncio.create_subprocess_exec = host(addr, route)
    return asyncio.run(netutil.get_local_network())


A32 = "2: eth0    inet 10.30.0.5/32 scope global eth0\n"

# a /32 with a link route on the same interface: the route says the network
got = read(A32, "default via 10.30.0.1 dev eth0 onlink\n10.30.0.0/23 dev eth0 proto static scope link\n")
assert got == ("10.30.0.0/23", "10.30.0.5"), got
assert netutil.last_network == "10.30.0.0/23", netutil.last_network

# a /32 with only an "onlink" default route: the /24 around the address
got = read(A32, "default via 10.30.0.1 dev eth0 onlink\n")
assert got == ("10.30.0.0/24", "10.30.0.5"), got

# a /31 is a host pair, not a network to watch: the same
got = read("2: eth0    inet 10.30.0.5/31 scope global eth0\n", "")
assert got == ("10.30.0.0/24", "10.30.0.5"), got

# a link route that does not hold the address, or one that is too wide, is not taken
got = read(A32, "10.99.0.0/24 dev eth0 scope link\n10.0.0.0/8 dev eth0 scope link\n")
assert got == ("10.30.0.0/24", "10.30.0.5"), got

# a normal prefix: as the address says, and the routes are not even asked
got = read("2: eth0    inet 10.20.2.50/22 brd 10.20.3.255 scope global dynamic eth0\n", "10.30.0.0/23 dev eth0 scope link\n")
assert got == ("10.20.0.0/22", "10.20.2.50"), got
assert asked == ["addr"], asked

print("check_local_network_host_prefix: ok")
