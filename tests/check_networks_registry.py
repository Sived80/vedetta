"""The registry of the networks (networks/registry.py) against what the app asks today.
1) differential: for every answer of `ip addr` (a /24, /27, /22, /16, /8, a /32, two addresses on the interface, a mask written oddly),
   registry.main() gives EXACTLY netutil.get_local_network(), and current().allowed gives EXACTLY netutil.filter_local_ips on 2000 addresses
   with a fixed seed; 2) when the host cannot be read both raise the same error; 3) the main network is confirmed, direct, first, never
   checked by model.validate (a /8 stays a /8); 4) nothing is written to disk.
Fake `ip addr`; invented private addresses only (10.x and 192.168.50-99.x).
    python tests/check_networks_registry.py"""
import asyncio
import ipaddress
import os
import random
import sys
import tempfile

DATA = tempfile.mkdtemp()
os.environ["VEDETTA_DATA_DIR"] = DATA
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import netutil  # noqa: E402
from app.networks import registry  # noqa: E402

ANSWER = {"text": ""}


class FakeProc:
    returncode = 0

    async def communicate(self, data=None):
        return ANSWER["text"].encode(), b""


async def fake_exec(*args, **kwargs):
    return FakeProc()


netutil.asyncio.create_subprocess_exec = fake_exec
netutil.lan_iface = lambda: "lan9"
rng = random.Random(20261108)


def line(addr: str) -> str:
    return "3: lan9    inet %s brd 0.0.0.0 scope global lan9\\       valid_lft forever preferred_lft forever\n" % addr


def sample(cidr: str, n: int = 2000) -> list:
    net = ipaddress.ip_network(cidr)
    lo, size = int(net.network_address), net.num_addresses
    out = [str(ipaddress.IPv4Address((lo - 300 + rng.randrange(min(size, 1 << 20) + 600)) % (1 << 32))) if rng.random() < 0.6
           else str(ipaddress.IPv4Address(rng.randrange(1 << 32))) for _ in range(n)]
    return out + [str(net.network_address), str(net.broadcast_address)]


async def both(text: str):
    ANSWER["text"] = text
    return await netutil.get_local_network(), await registry.main()


# 1) differential
CASES = [line("192.168.50.7/24"), line("192.168.50.70/27"), line("10.20.2.50/22"), line("10.20.2.50/16"), line("10.0.0.2/8"), line("10.9.9.9/32"),
         line("192.168.51.4/24") + line("192.168.52.4/24")]
for text in CASES:
    old, new = asyncio.run(both(text))
    assert new == old, (text, old, new)
    addrs = sample(old[0])
    allowed_old = asyncio.run(netutil.filter_local_ips(addrs))
    scope = asyncio.run(registry.current())
    assert scope.allowed(addrs) == allowed_old, text
    assert len(scope.networks) == 1 and str(scope.networks[0].cidr) == old[0], scope

# 2) the host cannot be read: the same error from both
for text in ("", "3: lan9    inet6 fd00::5/64 scope global\n", "garbage"):
    ANSWER["text"] = text
    errors = []
    for call in (netutil.get_local_network, registry.main, registry.current):
        try:
            asyncio.run(call())
        except Exception as exc:
            errors.append((type(exc), getattr(exc, "status_code", None)))
        else:
            errors.append(None)
    assert errors[0] is not None and errors == [errors[0]] * 3, (text, errors)

# 3) the main network as a Network
ANSWER["text"] = line("10.0.0.2/8")
main = asyncio.run(registry.current()).networks[0]
assert main.id == registry.MAIN_ID and main.state == "confirmed" and main.via == frozenset({"direct"}) and str(main.cidr) == "10.0.0.0/8", main
assert asyncio.run(registry.current()).network_of("10.200.1.5") == main, "the guard allows the whole main network, as filter_local_ips does"

# 4) nothing on disk (the log of the app aside: the error of 2) is logged)
assert [f for f in os.listdir(DATA) if f != "dashboard.log"] == [], os.listdir(DATA)

print("check_networks_registry: ok")
