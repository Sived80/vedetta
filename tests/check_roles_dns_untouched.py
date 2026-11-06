"""Issue #21: the DNS role check (one DNS query to every address the ARP sees) must leave alone the ignored devices and the cards that must not be touched
(touch_policy "none"), as the SSDP search already does. The gateway is always asked (it is the router), the computer the app runs on never.
Checked with fake primitives: the addresses passed to dns_servers() are recorded.
    python tests/check_roles_dns_untouched.py"""
import asyncio
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
try:
    import app.applog  # noqa: F401
except Exception:
    import logging
    stub = types.ModuleType("app.applog")
    stub.logger = logging.getLogger("dashboard")
    sys.modules["app.applog"] = stub

from app.recognition import roles  # noqa: E402

GW, OWN, PLAIN, IGNORED, FRAGILE = "10.0.0.1", "10.0.0.2", "10.0.0.20", "10.0.0.30", "10.0.0.40"
ARP = {ip: {"ip": ip, "mac": "AA:BB:CC:00:00:%02X" % int(ip.rsplit(".", 1)[1])} for ip in (GW, OWN, PLAIN, IGNORED, FRAGILE)}
ASKED: list = []


async def fake_dns_servers(candidates):
    ASKED.extend(candidates)
    return []


roles.dns_servers = fake_dns_servers
roles.default_gateway = lambda: GW
roles.devices_config.load_devices = lambda: [{"id": "f", "ip": FRAGILE, "touch": "none"}, {"id": "p", "ip": PLAIN}]
roles.touch_policy.may_touch = lambda d: d.get("touch") != "none"
roles.blocklist.matches = lambda mac=None, ip=None, name=None: ip in (IGNORED, GW)   # the gateway on the list too: it is still asked


async def main() -> None:
    await roles._compute_roles_snapshot({}, dict(ARP), OWN)
    asked = set(ASKED)
    assert PLAIN in asked, ASKED
    assert GW in asked, "the gateway must always be asked: %r" % ASKED
    assert IGNORED not in asked, "an ignored device was asked: %r" % ASKED
    assert FRAGILE not in asked, "a card that must not be touched was asked: %r" % ASKED
    assert OWN not in asked, ASKED


asyncio.run(main())
print("TUTTO OK")
