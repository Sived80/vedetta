"""A network behind the router set to "presence only" is never searched in depth (registry.allowed refuses its addresses): the page must
know it, or the deep search badge counts devices that can never be analysed and its number never goes down (first report on 1.0.0).
1) every card of /api/ha/devices and of a live "device" event says deep_ok: True on the main network and on a "ports" network, False on a
   "presence" network and outside every network; 2) while the main network is not known yet nothing is marked (the page keeps counting them);
3) registry.allowed names the "presence only" network in its warning, and keeps the old warning, word for word, for an address outside.
Invented private addresses only.
    python tests/check_deep_presence.py"""
import asyncio
import logging
import os
import sys
import tempfile

DATA = tempfile.mkdtemp()
os.environ["VEDETTA_DATA_DIR"] = DATA
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import netutil  # noqa: E402
from app.applog import logger  # noqa: E402
from app.networks import registry  # noqa: E402
from app.routes import ha as ha_routes  # noqa: E402
from app.storage import network_store  # noqa: E402

MAIN, PRESENCE, PORTS, OUTSIDE = "10.40.0.5", "10.41.0.7", "10.42.0.9", "10.49.0.1"
netutil.last_network = "10.40.0.0/24"
main_net = registry.main_network("10.40.0.0/24")
network_store.add({"id": "n41", "cidr": "10.41.0.0/24", "via": ["routed"], "touch": "presence", "state": "confirmed"}, main_net)
network_store.add({"id": "n42", "cidr": "10.42.0.0/24", "via": ["routed"], "touch": "ports", "state": "confirmed"}, main_net)

failed = 0


def check(cond, msg):
    global failed
    print(("ok: " if cond else "FAILED: ") + msg)
    failed += 0 if cond else 1


cards = [{"id": ip, "ip": ip} for ip in (MAIN, PRESENCE, PORTS, OUTSIDE)]
marked = {c["ip"]: c.get("deep_ok") for c in ha_routes.with_deep(cards)}
check(marked == {MAIN: True, PRESENCE: False, PORTS: True, OUTSIDE: False}, f"the device list says who may be searched in depth: {marked}")
check(all("deep_ok" not in c for c in cards), "the cards given are not changed")

event = {"type": "device", "device": {"id": "d1", "ip": PRESENCE, "name": "Plug"}}
live = ha_routes.localize(event, {})
check(live["device"].get("deep_ok") is False, "a live update of one device says it too (else the badge would count it again)")

netutil.last_network = None
check(all("deep_ok" not in c for c in ha_routes.with_deep(cards)), "main network not known yet: nothing marked")
netutil.last_network = "10.40.0.0/24"


class Grab(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


grab = Grab()
logger.addHandler(grab)


async def fake_current():
    return registry.scope_of("10.40.0.0/24")


registry.current = fake_current
kept = asyncio.run(registry.allowed([MAIN, PRESENCE, OUTSIDE]))
check(kept == [MAIN], f"only the main address is searched: {kept}")
check(any(PRESENCE in line and "presenza" in line for line in grab.lines), f"the warning names the 'presence only' network: {grab.lines}")
check(any(line == f"Scansione rifiutata, IP fuori dalla rete locale 10.40.0.0/24: {OUTSIDE}" for line in grab.lines),
      "an address outside every network keeps the old warning word for word")
check(not any(PRESENCE in line and "fuori dalla rete locale" in line for line in grab.lines), "the presence address is not called 'outside'")

print("ALL OK" if not failed else f"{failed} FAILED")
sys.exit(1 if failed else 0)
