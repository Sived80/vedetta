"""Response time of a host that drops ping: the ARP round trip is used, and a silent host stays empty."""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import latency  # noqa: E402

# nmap output -> milliseconds
assert abs(latency.parse_nmap_latency("Nmap scan report for 10.0.0.9\nHost is up (0.00042s latency).\n") - 0.42) < 1e-9
assert latency.parse_nmap_latency("Note: Host seems down.\n") is None

# ARP table: only complete entries (flags 0x2) count
table = os.path.join(tempfile.mkdtemp(), "arp")
with open(table, "w", encoding="ascii") as f:
    f.write("IP address       HW type     Flags       HW address            Mask     Device\n"
            "10.0.0.117       0x1         0x2         aa:bb:cc:00:00:01     *        eth0\n"
            "10.0.0.118       0x1         0x0         00:00:00:00:00:00     *        eth0\n")
assert latency.arp_known("10.0.0.117", table) and not latency.arp_known("10.0.0.118", table)
assert not latency.arp_known("10.0.0.99", table) and not latency.arp_known("10.0.0.1", table + ".missing")

# measure(): ping first, ARP only when ping got nothing
calls = []


async def ping_none(ip, timeout):
    calls.append(("icmp", ip))
    return None


async def ping_ok(ip, timeout):
    calls.append(("icmp", ip))
    return 4.0


async def arp_ok(ip, timeout=3.0):
    calls.append(("arp", ip))
    return 0.7


async def arp_none(ip, timeout=3.0):
    calls.append(("arp", ip))
    return None


real_arp_ms = latency._arp_ms
latency._PING = "ping"
latency._icmp_ms, latency._arp_ms = ping_ok, arp_ok
assert asyncio.run(latency.measure("10.0.0.5")) == 4.0 and calls == [("icmp", "10.0.0.5")]   # ping answers: no ARP

calls.clear()
latency._icmp_ms, latency._arp_ms = ping_none, arp_ok
assert asyncio.run(latency.measure("10.0.0.117")) == 0.7 and calls == [("icmp", "10.0.0.117"), ("arp", "10.0.0.117")]

latency._icmp_ms, latency._arp_ms = ping_none, arp_none
assert asyncio.run(latency.measure("10.0.0.118")) is None                       # nothing answers: stays empty

# without nmap the real function gives None and does not run anything
latency._NMAP = None
assert asyncio.run(real_arp_ms("10.0.0.117")) is None
print("TUTTO OK")
