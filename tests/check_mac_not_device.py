# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""MACs that are not a device never enter Vedetta (standards only, IEEE 802-2014 section 8.2: the I/G bit, the least significant bit of the
first octet, marks a group address): the all-zero MAC, the broadcast FF:FF:FF:FF:FF:FF and every multicast MAC (01:00:5E:.. of IPv4 multicast,
RFC 1112; 33:33:.. of IPv6 multicast, RFC 2464). They could inflate the count of devices or make cards. Kept: VRRP's virtual router MAC
00:00:5E:00:01:xx (RFC 5798, a unicast MAC) and any locally administered unicast MAC. Every entry point drops them, with one log line per
MAC. Invented values only, no network."""
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import macaddr  # noqa: E402
from app.ha import ha_registry  # noqa: E402
from app.scan import arpplan, dhcp, scan_arp, snmp  # noqa: E402
from app.scan.adapters import generic  # noqa: E402
from app.storage import newdevices  # noqa: E402

NOT_DEVICES = ["00:00:00:00:00:00", "FF:FF:FF:FF:FF:FF", "ff-ff-ff-ff-ff-ff", "01:00:5E:00:00:FB", "01:00:5e:7f:ff:fa", "33:33:00:00:00:01",
               "33:33:FF:00:00:07", "03:00:00:00:00:01", "01:80:C2:00:00:00"]
DEVICES = ["02:00:00:00:00:01", "00:00:5E:00:01:0A", "0A:00:00:00:00:02", "F2:00:00:00:00:03", "BA:BE:00:00:00:04"]
for m in NOT_DEVICES:
    assert not macaddr.is_device_mac(m), m
    assert newdevices.normalize_mac(m) is None, m
for m in DEVICES:
    assert macaddr.is_device_mac(m), m
assert not macaddr.is_device_mac(None) and not macaddr.is_device_mac("") and not macaddr.is_device_mac("not a mac")

# arp-scan: a multicast or broadcast answer is not a host, nor a second MAC of one
out = "\n".join(["192.0.2.10\t02:00:00:00:00:10\t(Unknown)", "192.0.2.11\t01:00:5e:00:00:fb\t(Unknown)", "192.0.2.10\tff:ff:ff:ff:ff:ff\t(Unknown)",
                 "192.0.2.12\t00:00:00:00:00:00\t(Unknown)", "192.0.2.13\t00:00:5e:00:01:0a\t(Unknown)"])
hosts = scan_arp.parse_arp_scan(out)
assert [(h["ip"], h["mac"]) for h in hosts] == [("192.0.2.10", "02:00:00:00:00:10"), ("192.0.2.13", "00:00:5E:00:01:0A")], hosts
assert "also" not in hosts[0], hosts[0]

# the neighbour table
neigh = "\n".join(["192.0.2.20 dev eth0 lladdr 33:33:00:00:00:01 REACHABLE", "192.0.2.21 dev eth0 lladdr 02:00:00:00:00:21 REACHABLE",
                   "192.0.2.22 dev eth0 lladdr 00:00:00:00:00:00 STALE"])
assert [e["ip"] for e in arpplan.parse_neighbor_entries(neigh)] == ["192.0.2.21"]

# DHCP: a request whose chaddr is a group address is no client
def request(chaddr: bytes) -> bytes:
    p = bytearray(300)
    p[0] = 1
    p[28:34] = chaddr
    p[236:240] = dhcp._MAGIC_COOKIE
    p[240:243] = bytes([53, 1, 3])
    p[243] = 255
    return bytes(p)


assert dhcp.parse(request(bytes.fromhex("020000000030")))[0] == "02:00:00:00:00:30"
assert dhcp.parse(request(bytes.fromhex("01005e0000fb"))) is None
assert dhcp.parse(request(bytes(6))) is None

# the router's table (SNMP)
assert snmp.mac_text(bytes.fromhex("01005e0000fb")) is None and snmp.mac_text(bytes.fromhex("333300000001")) is None
assert snmp.mac_text(bytes.fromhex("020000000040")) == "02:00:00:00:00:40"

# Home Assistant's registry
dev = {"connections": [["mac", "01:00:5e:00:00:fb"], ["mac", "02:00:00:00:00:50"], ["mac", "ff:ff:ff:ff:ff:ff"]]}
assert ha_registry._macs_of(dev) == ["02:00:00:00:00:50"]


# the MAC a generic probe reads for one address
class Proc:
    def __init__(self, text):
        self.text = text

    async def communicate(self):
        return self.text.encode(), b""


async def read_mac(text):
    async def fake_exec(*a, **k):
        return Proc(text)
    real = generic.asyncio.create_subprocess_exec
    generic.asyncio.create_subprocess_exec = fake_exec
    try:
        return await generic._get_mac("192.0.2.60")
    finally:
        generic.asyncio.create_subprocess_exec = real

assert asyncio.run(read_mac("192.0.2.60 dev eth0 lladdr 01:00:5e:00:00:fb REACHABLE")) is None
assert asyncio.run(read_mac("192.0.2.60 dev eth0 lladdr 02:00:00:00:00:60 REACHABLE")) == "02:00:00:00:00:60"

# one log line per MAC dropped, not one per reading
lines = []


class Catch(logging.Handler):
    def emit(self, record):
        lines.append(record.getMessage())


logging.getLogger("dashboard").addHandler(Catch())
macaddr._logged.clear()
for _ in range(3):
    scan_arp.parse_arp_scan("192.0.2.70\t01:00:5e:00:00:71\t(Unknown)")
assert len([x for x in lines if "01:00:5E:00:00:71" in x.upper()]) == 1, lines

print("OK mac not device")
