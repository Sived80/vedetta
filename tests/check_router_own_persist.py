# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The router's own addresses read through SNMP (IP-MIB) are kept in the data folder: after a restart the twins by SNMP (the router's address on
each VLAN) are there at once, not after the first sweep of the networks behind the router (up to 15 minutes later). Kept only for the router
they were read from; a newer reading replaces them; without SNMP nothing is known. No network: the SNMP answers are fakes. Invented values."""
import asyncio
import importlib
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import router_arp, snmp  # noqa: E402
from app.storage import settings  # noqa: E402

OWN = {"10.71.0.1", "10.71.20.1", "10.71.30.1"}


async def fake_arp(host, community, **kw):
    return {"10.71.20.5": "02:00:00:00:71:05"}


async def fake_own(host, community, **kw):
    return set(OWN)


def restart():
    """A new start of the service: the module state is born again, the SNMP answers stay fakes (and are never asked here)."""
    global router_arp
    router_arp = importlib.reload(router_arp)


async def never(*a, **kw):
    raise AssertionError("SNMP asked at start")

snmp.arp_table, snmp.own_addresses = fake_arp, fake_own
settings.snmp_update({"snmp_router": "10.71.0.1", "snmp_community": "s3cret"})
assert asyncio.run(router_arp.table())
assert router_arp.own_addresses() == ("10.71.0.1", frozenset(OWN))

# after a restart, before any reading: the last list, at once
snmp.arp_table, snmp.own_addresses = never, never
restart()
assert router_arp.own_addresses() == ("10.71.0.1", frozenset(OWN)), router_arp.own_addresses()

# a newer reading replaces it (here the router no longer gives its list)
snmp.arp_table = fake_arp


async def refused(host, community, **kw):
    raise snmp.SnmpError("refused")
snmp.own_addresses = refused
asyncio.run(router_arp.table())
assert router_arp.own_addresses() == ("10.71.0.1", frozenset())
snmp.arp_table, snmp.own_addresses = never, never
restart()
assert router_arp.own_addresses() == ("10.71.0.1", frozenset())

# kept for the router it was read from: another router written, nothing known until it is read
snmp.arp_table, snmp.own_addresses = fake_arp, fake_own
asyncio.run(router_arp.table())
settings.snmp_update({"snmp_router": "10.71.0.254", "snmp_community": "s3cret"})
restart()
assert router_arp.own_addresses() == ("10.71.0.254", frozenset())

# SNMP switched off: nothing
settings.snmp_update({"snmp_router": "10.71.0.1", "snmp_community": ""})
restart()
assert router_arp.own_addresses() == (None, frozenset())

# a damaged file is no list
settings.snmp_update({"snmp_router": "10.71.0.1", "snmp_community": "s3cret"})
router_arp.OWN_PATH.write_text("{not json", encoding="utf-8")
restart()
assert router_arp.own_addresses() == ("10.71.0.1", frozenset())

print("OK router own persist")
