# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""Issue #57: a card whose brand comes from the MAC prefix must show that MAC. The probe asks the brand with the MAC it remembers (the link, else
the last MAC seen), but the card kept only the MAC of this check's answer: a phone that is asleep (no answer, no ARP entry), or a device that
answers its port while the neighbour table has no entry for it, showed "Brand · MAC prefix" with no MAC row. Invented values only."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import ha_data  # noqa: E402
from app.recognition import roles  # noqa: E402
from app.scan import probe  # noqa: E402

roles.roles_for = lambda ip: []
roles.upnp_types = lambda ip: []

REMEMBERED = "F8:54:B8:00:00:C1"     # a prefix whose maker is a product brand (role "brand" in the tables), the rest invented


def card(adapter_result, arp):
    """The page's card after one check: the adapter answers `adapter_result`, the ARP view is `arp` (no network is touched)."""
    async def adapter(ip, port):
        return dict(adapter_result)

    async def arp_view():
        return arp

    async def run():
        probe.ADAPTERS = {"generic": adapter}
        dev = {"id": "c57", "name": "192.0.2.57", "ip": "192.0.2.57", "port": 80, "adapter": "generic", "scan_info": {}, "last_mac": REMEMBERED}
        return await probe.probe_device(dev, asyncio.ensure_future(arp_view()))
    return ha_data.compact_device(asyncio.run(run()))


# asleep: no answer, no ARP entry; the brand still comes from the remembered MAC
c = card({"online": False}, {})
assert c["brand"] and c["brand_source"] == "oui", c
assert c["mac"] == REMEMBERED, ("brand from the MAC prefix but no MAC on the card", c["mac"])
assert not c["online"]

# online by its port while the neighbour table has no entry for it
c = card({"online": True}, {})
assert c["online"] and c["brand_source"] == "oui", c
assert c["mac"] == REMEMBERED, ("online card, brand from the MAC prefix, no MAC", c["mac"])

# the MAC of this check's answer still wins over the remembered one (a rotating private MAC shows the current one)
c = card({"online": False}, {"192.0.2.57": {"ip": "192.0.2.57", "mac": "F8:54:B8:00:00:C2", "vendor": None}})
assert c["online"] and c["mac"] == "F8:54:B8:00:00:C2", c["mac"]

# a card that never had a MAC (behind the router) stays without one
probe.ADAPTERS = {}
res = asyncio.run(probe.probe_device({"id": "r", "name": "198.51.100.7", "ip": "198.51.100.7", "port": 80, "adapter": "generic", "scan_info": {}}))
assert ha_data.compact_device(res)["mac"] is None

print("OK card mac when absent")
