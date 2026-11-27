# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The router's ARP table in use (scan/router_arp.py, routedwatch): off until the person writes the router's address and a community
(never tried on its own); the community never comes back from the API; a reading fills the MACs of the sweep behind the router, with
Home Assistant's trackers first; a failure is kept for the page and said once; «Try» says how many addresses or why not.
    python tests/check_router_arp.py"""
import asyncio
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import routedwatch  # noqa: E402
from app.scan import router_arp, snmp  # noqa: E402
from app.storage import settings  # noqa: E402

asked = []


async def fake_arp(host, community, **kw):
    asked.append((host, community))
    if community == "wrong":
        raise asyncio.TimeoutError()
    return {"192.168.20.5": "AA:BB:CC:00:00:05", "192.168.20.6": "AA:BB:CC:00:00:06"}


async def fake_own(host, community, **kw):
    return set()                 # the router's own addresses (check_router_own_addresses.py): never a real packet from a test

snmp.arp_table, snmp.own_addresses = fake_arp, fake_own

# 1) off by default: nothing asked, «Try» says so
assert not router_arp.configured() and asyncio.run(router_arp.table()) == {} and asked == []
assert asyncio.run(router_arp.test()) == {"ok": False, "error": "not_configured"}

# 2) settings: validated, the community never in an answer, kept when only the address changes
# 19/11: the community travels in clear (v2c): never to a public address, a broadcast, a multicast, the loopback or 0.0.0.0
for bad in ({"snmp_router": "router.lan"}, {"snmp_router": "300.1.1.1"}, {"snmp_community": "x" * 65}, {"snmp_community": 5}, {"snmp_community": "a\nb"},
            {"snmp_router": "8.8.8.8"}, {"snmp_router": "255.255.255.255"}, {"snmp_router": "224.0.0.1"}, {"snmp_router": "127.0.0.1"},
            {"snmp_router": "0.0.0.0"}, {"snmp_router": "100.64.0.1"}, {"snmp_router": "169.254.1.1"}, {"snmp_router": "192.168.1.255"},
            {"snmp_router": "010.0.0.1"}, {"snmp_router": " 10.0.0.1"}):
    try:
        settings.snmp_update(bad)
        raise AssertionError(bad)
    except ValueError:
        pass
pub = settings.snmp_update({"snmp_router": "192.168.1.1", "snmp_community": "s3cret"})
assert pub == {"snmp_router": "192.168.1.1", "snmp_community_set": True} and "s3cret" not in str(router_arp.status())
settings.snmp_update({"snmp_router": "192.168.1.254"})
assert settings.snmp_load() == {"snmp_router": "192.168.1.254", "snmp_community": "s3cret"}
settings.update({"poll_interval": 60})
settings.sentinel_update({"ha_events": False})
assert settings.snmp_load()["snmp_community"] == "s3cret"                       # other saves keep it

# 3) a reading, and «Try»
assert asyncio.run(router_arp.table()) == {"192.168.20.5": "AA:BB:CC:00:00:05", "192.168.20.6": "AA:BB:CC:00:00:06"}
assert asked[-1] == ("192.168.1.254", "s3cret")
assert asyncio.run(router_arp.test()) == {"ok": True, "rows": 2, "error": None}

# 4) a failure: kept for the page, the table empty, «Try» says why
settings.snmp_update({"snmp_community": "wrong"})
assert asyncio.run(router_arp.table()) == {} and router_arp.status()["last_error"] == "TimeoutError"
assert asyncio.run(router_arp.test())["ok"] is False

# 5) in the sweep: the router's MACs in the shape of the trackers, Home Assistant first
from_router = routedwatch._from_router({"192.168.20.5": "aa-bb-cc-00-00-05", "192.168.20.7": "nonsense"})
assert from_router == {"192.168.20.5": {"mac": "AA:BB:CC:00:00:05", "host": None, "name": None}}, from_router
merged = {**from_router, **{"192.168.20.5": {"mac": "11:22:33:44:55:66", "host": "nas", "name": "NAS"}}}
assert merged["192.168.20.5"]["mac"] == "11:22:33:44:55:66"

# 6) the routes
from fastapi.testclient import TestClient  # noqa: E402
from app import main  # noqa: E402
client = TestClient(main.app)
r = client.post("/api/snmp", json={"snmp_router": "192.168.1.1", "snmp_community": "s3cret"})
assert r.status_code == 200 and r.json()["snmp_community_set"] is True and "s3cret" not in r.text
assert "s3cret" not in client.get("/api/snmp").text
assert client.post("/api/snmp", json={"snmp_router": "x"}).status_code == 400
assert client.post("/api/snmp/test").json()["ok"] is True
print("check_router_arp: ok")
