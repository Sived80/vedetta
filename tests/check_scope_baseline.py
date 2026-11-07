"""Characterization of the network guard of today (one network only), before the work on more networks: it is the reference of the differential test of the
guard that will replace it. Asserts what the code does now: get_local_network asks `ip -o -4 addr show <lan_iface()>` and reads the first address; filter_local_ips keeps
the addresses inside that network, in the order given, drops the others, and the network and broadcast addresses count as inside; an empty list stays empty; a value that is not
an IPv4 address raises ValueError (the routes check it before). 3000 addresses with a fixed seed are compared with a truth computed with integers, without the ipaddress module.
Fake `ip addr` output; private and documentation addresses only.
    python tests/check_scope_baseline.py"""
import asyncio
import os
import random
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import netutil  # noqa: E402

CALLS: list = []


class FakeProc:
    def __init__(self, text: str):
        self.text = text

    async def communicate(self):
        return self.text.encode(), b""


def reading(text: str):
    async def fake(*args, **kwargs):
        CALLS.append(args)
        return FakeProc(text)
    return fake


netutil.lan_iface = lambda: "lan9"
netutil.asyncio.create_subprocess_exec = reading("3: lan9    inet 10.0.4.20/23 brd 10.0.5.255 scope global lan9\n    inet 10.9.9.9/24 scope global secondary lan9\n")

# 1) the reading: the command, the interface, the first address only
assert asyncio.run(netutil.get_local_network()) == ("10.0.4.0/23", "10.0.4.20")
assert CALLS[-1] == ("ip", "-o", "-4", "addr", "show", "lan9"), CALLS


def ip_to_int(ip: str) -> int:
    a, b, c, d = (int(x) for x in ip.split("."))
    return (a << 24) | (b << 16) | (c << 8) | d


def inside(ip: str) -> bool:
    """Truth without the code under test: 10.0.4.0/23 = the 512 addresses from 10.0.4.0 to 10.0.5.255."""
    return ip_to_int("10.0.4.0") <= ip_to_int(ip) <= ip_to_int("10.0.5.255")


run = lambda ips: asyncio.run(netutil.filter_local_ips(ips))  # noqa: E731

# 2) inside / outside, order kept, edges of the network
given = ["10.0.5.7", "192.0.2.1", "10.0.4.0", "10.0.3.255", "10.0.5.255", "10.0.6.0", "10.0.4.1"]
assert run(given) == ["10.0.5.7", "10.0.4.0", "10.0.5.255", "10.0.4.1"], run(given)

# 3) empty world
assert run([]) == []

# 4) a value that is not an address: today it raises (the callers validate first)
for bad in ("10.0.4.300", "lan", "", "10.0.4.1/24"):
    try:
        run([bad])
    except ValueError:
        continue
    raise AssertionError("not an address but accepted: %r" % bad)

# 5) differential against the integer truth, fixed seed
rng = random.Random(20261107)
sample = []
for _ in range(3000):
    if rng.random() < 0.5:
        n = ip_to_int("10.0.4.0") - 64 + rng.randrange(512 + 128)   # around the edges
    else:
        n = rng.randrange(1 << 32)
    sample.append(".".join(str((n >> s) & 255) for s in (24, 16, 8, 0)))
expected = [ip for ip in sample if inside(ip)]
assert run(sample) == expected, "the guard differs from the truth"
assert 0 < len(expected) < len(sample)

# 6) the guard asks the network again at every call (no cache): a new reading counts at once
netutil.asyncio.create_subprocess_exec = reading("3: lan9    inet 192.168.50.2/24 scope global lan9\n")
assert run(["10.0.4.1", "192.168.50.9"]) == ["192.168.50.9"]

print("check_scope_baseline: ok")
