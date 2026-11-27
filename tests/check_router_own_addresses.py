# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The router's own addresses through SNMP (1.0.1): with the router's address and a community written, the reading of its ARP table also reads
its own address list (IP-MIB ipAdEntAddr, else ipAddressTable), read-only, with the same community. Every card at one of those addresses on
another network is a twin of the router's card on the main network (the address written as SNMP router). Nothing changes without SNMP.
    python tests/check_router_own_addresses.py"""
import asyncio
import ipaddress
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import twins  # noqa: E402
from app.networks.model import Network  # noqa: E402
from app.networks.scope import Scope  # noqa: E402
from app.scan import router_arp, snmp  # noqa: E402
from app.storage import settings  # noqa: E402


def router(table: dict, error_for=None):
    """A fake router answering GETBULK from a table of OIDs; `error_for` = a subtree it refuses with an error-status."""
    ordered = sorted(table)
    seen = []

    async def ask(packet):
        _, msg, _ = snmp._read(packet, 0)
        _, _, pdu = snmp._children(msg)
        fields = snmp._children(pdu[1])
        rid = int.from_bytes(fields[0][1], "big", signed=True)
        reps = int.from_bytes(fields[2][1], "big")
        start = snmp.decode_oid(snmp._children(snmp._children(fields[3][1])[0][1])[0][1])
        seen.append((pdu[0], start))
        assert pdu[0] in (snmp.GET_NEXT, snmp.GET_BULK)                     # read only
        error = 2 if error_for and start[:len(error_for)] == error_for else 0
        nxt = [o for o in ordered if o > start][:max(1, reps)]
        binds = b"".join(snmp.tlv(0x30, snmp.oid(o) + snmp.tlv(0x40, table[o])) for o in nxt)
        if len(nxt) < max(1, reps):
            binds += snmp.tlv(0x30, snmp.oid(start + (9,)) + snmp.tlv(0x82, b""))
        pdu = snmp.tlv(snmp.RESPONSE, snmp.integer(rid) + snmp.integer(error) + snmp.integer(0) + snmp.tlv(0x30, binds))
        return snmp.tlv(0x30, snmp.integer(1) + snmp.octets(b"s3cret") + pdu)
    ask.seen = seen
    return ask


# 1) the reader: the old table (index = the address), the newer one (index = type 1 . length 4 . address); loopback dropped
A1 = (1, 3, 6, 1, 2, 1, 4, 20, 1, 1)
old = {A1 + ip: bytes(ip) for ip in ((10, 70, 0, 1), (10, 70, 20, 1), (10, 70, 30, 1), (127, 0, 0, 1))}
old[(1, 3, 6, 1, 2, 1, 4, 21, 1, 1, 0, 0, 0, 0)] = b"\x00" * 4                          # outside the subtree
assert asyncio.run(snmp.own_addresses("x", "s3cret", ask=router(old))) == {"10.70.0.1", "10.70.20.1", "10.70.30.1"}
A2 = (1, 3, 6, 1, 2, 1, 4, 34, 1, 3)
new = {A2 + (1, 4, 10, 70, 0, 1): b"\x00\x00\x00\x02", A2 + (1, 4, 10, 70, 40, 1): b"\x00\x00\x00\x03",
       A2 + (2, 16) + (0xFE, 0x80) + (0,) * 14: b"\x00\x00\x00\x02"}                    # an IPv6 one: not ours
assert asyncio.run(snmp.own_addresses("x", "s3cret", ask=router(new, error_for=A1))) == {"10.70.0.1", "10.70.40.1"}
assert asyncio.run(snmp.own_addresses("x", "s3cret", ask=router({}))) == set()

# 2) read with the ARP table, kept; not configured: nothing is asked, nothing is known
asked = []


async def fake_arp(host, community, **kw):
    asked.append(("arp", host))
    return {"10.70.20.5": "AA:BB:CC:00:00:05"}


async def fake_own(host, community, **kw):
    asked.append(("own", host, community))
    return {"10.70.0.1", "10.70.20.1", "10.70.30.1"}

snmp.arp_table, snmp.own_addresses = fake_arp, fake_own
assert asyncio.run(router_arp.table()) == {} and asked == [] and router_arp.own_addresses() == (None, frozenset())
settings.snmp_update({"snmp_router": "10.70.0.1", "snmp_community": "s3cret"})
assert asyncio.run(router_arp.table()) == {"10.70.20.5": "AA:BB:CC:00:00:05"}
assert ("own", "10.70.0.1", "s3cret") in asked
assert router_arp.own_addresses() == ("10.70.0.1", frozenset({"10.70.0.1", "10.70.20.1", "10.70.30.1"}))


async def own_refused(host, community, **kw):
    raise snmp.SnmpError("refused")
snmp.own_addresses = own_refused                         # the address list refused: the ARP table still counts
assert asyncio.run(router_arp.table()) == {"10.70.20.5": "AA:BB:CC:00:00:05"} and router_arp.status()["last_error"] is None
assert router_arp.own_addresses() == ("10.70.0.1", frozenset())

# 3) the twins: every card at one of the router's addresses on another network
MAIN = Network("main", ipaddress.ip_network("10.70.0.0/24"), frozenset({"direct"}), "full", "confirmed")
V20 = Network("lab20", ipaddress.ip_network("10.70.20.0/24"), frozenset({"router"}), "presence", "confirmed", vlan=20)
V30 = Network("lab30", ipaddress.ip_network("10.70.30.0/24"), frozenset({"router"}), "presence", "confirmed", vlan=30)
scope = Scope((MAIN, V20, V30))
cards = [{"id": "r0", "ip": "10.70.0.1", "mac": "02:5A:77:00:00:01"}, {"id": "r20", "ip": "10.70.20.1", "mac": None},
         {"id": "r30", "ip": "10.70.30.1", "mac": None}, {"id": "n", "ip": "10.70.30.9", "mac": None}]
own = ("10.70.0.1", frozenset({"10.70.0.1", "10.70.20.1", "10.70.30.1"}))
assert twins.find(cards, set(), None, frozenset(), scope.network_of, router=own) == {"r20": "r0", "r30": "r0"}
assert twins.find(cards, set(), None, frozenset(), scope.network_of) == {}                                   # without SNMP: as before
assert twins.find(cards, set(), None, frozenset(), scope.network_of, router=(None, own[1])) == {"r20": "r0", "r30": "r0"}   # the main-network card among them
assert twins.find(cards[1:], set(), None, frozenset(), scope.network_of, router=own) == {}                    # no card on the main network
assert twins.find(cards, set(), None, frozenset(), scope.network_of, router=("10.70.20.1", frozenset({"10.70.20.1", "10.70.30.1"}))) == {}

# 4) the step at the end of the cycle reads them
from app import identity_upkeep  # noqa: E402
from app.storage import devices_config  # noqa: E402
devices_config.add_devices([{"ip": c["ip"], "name": c["ip"]} for c in cards])
ids = {d["ip"]: d["id"] for d in devices_config.load_devices()}


class Fake(identity_upkeep.IdentityUpkeep):
    devices = {ids[c["ip"]]: {**c, "id": ids[c["ip"]], "online": True, "name": c["ip"]} for c in cards}
    _last_mac: dict = {}
    _rev_of: dict = {}
    _twin_of: dict = {}
    rev = 0

    def emit_event(self, event):
        pass


async def current():
    return scope


async def main_net():
    return "10.70.0.0/24", "10.70.0.50"

identity_upkeep.registry.current, identity_upkeep.registry.main = current, main_net
identity_upkeep.host_read.read_host = lambda: {"interfaces": [{"ipv4": [{"address": "10.70.0.50"}]}]}
identity_upkeep.macverdict.lenders = lambda: frozenset()
router_arp.own_addresses = lambda: own
fake = Fake()
asyncio.run(fake.name_twins())
assert fake._twin_of == {ids["10.70.20.1"]: "10.70.0.1", ids["10.70.30.1"]: "10.70.0.1"}, fake._twin_of
print("check_router_own_addresses: ok")
