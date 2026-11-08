"""The ARP round trip of the latency (nmap -sn -PR) only for an address of the network of the interface, learned on that interface
(K14, G0-19 of the study of the networks).

For an address that is not on the link, nmap does not do ARP: it falls back to its default probes (ICMP echo and timestamp, SYN to 443,
ACK to 80), seen in the simulator after a change of network (an old card still in the ARP table). Here nmap is a spy: it must run for a
card of the network whose entry is on the main interface, and never for an old address on the same interface, for an address of a VLAN
learned on another interface, or before the network is known. Invented private and documentation addresses only.
    python tests/check_no_nmap_default_probes_off_link.py"""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import netutil  # noqa: E402
from app.scan import latency  # noqa: E402
from app.networks import registry as _routes  # noqa: E402
_routes.ROUTE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "no-route-file")   # the fake network, not the routes of this computer

table = os.path.join(tempfile.mkdtemp(), "arp")
with open(table, "w", encoding="ascii") as f:
    f.write("IP address       HW type     Flags       HW address            Mask     Device\n"
            "192.168.50.10    0x1         0x2         aa:bb:cc:00:00:10     *        lan9\n"       # a card of the network
            "198.51.100.9     0x1         0x2         aa:bb:cc:00:00:01     *        lan9\n"       # a card of the network of before
            "192.168.60.20    0x1         0x2         aa:bb:cc:00:00:20     *        lan9.60\n")   # a device of a VLAN of the host
latency.ARP_TABLE = table
_real_known = latency.arp_known
latency.arp_known = lambda ip, table=table, **kw: _real_known(ip, table, **kw)
netutil.lan_iface = lambda: "lan9"
latency._NMAP = "nmap"
RAN: list = []


class Proc:
    returncode = 0

    async def communicate(self):
        return b"Host is up (0.00042s latency).\n", b""


async def spy_exec(*args, **kwargs):
    RAN.append(args[-1])
    return Proc()


latency.asyncio.create_subprocess_exec = spy_exec

netutil.last_network = None                           # the network is not known yet: no ARP probe at all
assert asyncio.run(latency._arp_ms("192.168.50.10")) is None and RAN == []

netutil.last_network = "192.168.50.0/24"
assert asyncio.run(latency._arp_ms("192.168.50.10")) is not None and RAN == ["192.168.50.10"]
for ip in ("198.51.100.9", "192.168.60.20", "192.168.50.99"):
    assert asyncio.run(latency._arp_ms(ip)) is None, ip
assert RAN == ["192.168.50.10"], ("nmap ran for an address off the link", RAN)
print("check_no_nmap_default_probes_off_link: ok")
