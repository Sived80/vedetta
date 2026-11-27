# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""Twin cards (twins.py, decision B of 18/11): the router of the house with its leg on VLAN 20 (same MAC), Home Assistant with an address on VLAN 20
(an address of the host itself, no MAC). The twin takes the main card's name and the network, never over a name chosen by hand, and gives it
back when it is no longer a twin; the page gets the main card's address to put the twin next to it."""
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

MAIN = Network("main", ipaddress.ip_network("10.40.1.0/24"), frozenset({"direct"}), "full", "confirmed")
IOT = Network("lab20", ipaddress.ip_network("10.40.20.0/24"), frozenset({"router"}), "presence", "confirmed", vlan=20)
scope = Scope((MAIN, IOT))
R_MAC = "02:5A:11:00:00:E1"
cards = [{"id": "r1", "ip": "10.40.1.1", "mac": R_MAC, "name": "Gateway-1"}, {"id": "r20", "ip": "10.40.20.1", "mac": R_MAC.lower(), "name": "Gateway-1"},
         {"id": "ha", "ip": "10.40.1.100", "mac": None, "name": "Home Assistant"}, {"id": "ha20", "ip": "10.40.20.100", "mac": None, "name": "esphome-builder-1a2b3c4d"},
         {"id": "x", "ip": "10.40.20.50", "mac": "AA:BB:CC:00:00:01", "name": "Shelly"}]
host = {"10.40.1.100", "10.40.20.100", "172.30.32.1"}

pairs = twins.find(cards, host, "10.40.1.100", frozenset(), scope.network_of)
assert pairs == {"r20": "r1", "ha20": "ha"}, pairs
assert twins.find(cards, host, "10.40.1.100", frozenset({R_MAC}), scope.network_of) == {"ha20": "ha"}       # a lent MAC says nothing
two_on_main = cards + [{"id": "r1b", "ip": "10.40.1.2", "mac": R_MAC, "name": "x"}]
assert "r1b" not in twins.find(two_on_main, host, "10.40.1.100", frozenset(), scope.network_of)              # same network: not a twin (a repeater, a NAT)
assert twins.find(cards, host, None, frozenset(), scope.network_of) == {"r20": "r1"}                           # own address unknown: no host twins
outside = [{"id": "o", "ip": "10.5.0.1", "mac": R_MAC, "name": "o"}, cards[0]]
assert twins.find(outside, set(), None, frozenset(), scope.network_of) == {}                                   # an address in no network
assert twins.name("Home Assistant", IOT) == "Home Assistant (VLAN 20)"
named = Network("lab20", IOT.cidr, IOT.via, IOT.touch, IOT.state, name="IoT", vlan=20)
assert twins.name("Gateway-1", named) == "Gateway-1 (IoT)"
assert twins.name("Gateway-1", Network("n", IOT.cidr, IOT.via, IOT.touch, IOT.state)) == "Gateway-1 (10.40.20.0/24)"
assert twins.name(None, IOT) is None and twins.name("x", None) is None

# --- the step at the end of the cycle, on the real cards file
from app.storage import devices_config  # noqa: E402
from app import identity_upkeep  # noqa: E402

devices_config.add_devices([{"ip": c["ip"], "name": c["ip"]} for c in cards])    # as the scan does: the address first, then the name it finds
saved = {d["ip"]: d for d in devices_config.load_devices()}
for c in cards:
    devices_config.update_auto_name(saved[c["ip"]]["id"], c["name"], "mdns")
devices_config.update_device(saved["10.40.20.50"]["id"], "Shelly")          # a name chosen by hand
mem = {saved[c["ip"]]["id"]: {**c, "id": saved[c["ip"]]["id"]} for c in cards}


EVENTS = []


class Fake(identity_upkeep.IdentityUpkeep):
    devices = mem
    _last_mac: dict = {}
    _rev_of: dict = {}
    _twin_of: dict = {}
    rev = 0

    def emit_event(self, event):
        EVENTS.append(event)


async def current():
    return scope


async def main_net():
    return "10.40.1.0/24", "10.40.1.100"

identity_upkeep.registry.current, identity_upkeep.registry.main = current, main_net
identity_upkeep.host_read.read_host = lambda: {"interfaces": [{"ipv4": [{"address": ip}]} for ip in host]}
identity_upkeep.macverdict.lenders = lambda: frozenset()
fake = Fake()
asyncio.run(fake.name_twins())
after = {d["ip"]: d for d in devices_config.load_devices()}
assert after["10.40.20.100"]["name"] == "Home Assistant (VLAN 20)" and after["10.40.20.100"]["name_source"] == "twin", after["10.40.20.100"]
assert after["10.40.20.1"]["name"] == "Gateway-1 (VLAN 20)"
assert after["10.40.1.1"]["name"] == "Gateway-1" and after["10.40.20.50"]["name"] == "Shelly"
ha20 = mem[saved["10.40.20.100"]["id"]]
assert {e["id"] for e in EVENTS} == {saved["10.40.20.100"]["id"], saved["10.40.20.1"]["id"]}, EVENTS      # each twin sent to the page once
assert fake._twin_of == {saved["10.40.20.100"]["id"]: "10.40.1.100", saved["10.40.20.1"]["id"]: "10.40.1.1"}
EVENTS.clear()
asyncio.run(fake.name_twins())
assert EVENTS == [], EVENTS                                     # nothing changed: nothing sent again (18/11 review: a twin was sent every cycle)
# the main router offline: its live result has no MAC, its last MAC keeps the pair (18/11 review: the twin lost its name at every outage)
r1 = saved["10.40.1.1"]["id"]
fake._last_mac[r1] = R_MAC
mem[r1] = {**mem[r1], "mac": None}
asyncio.run(fake.name_twins())
assert EVENTS == [] and mem[saved["10.40.20.1"]["id"]]["name"] == "Gateway-1 (VLAN 20)", EVENTS
assert ha20["name"] == "Home Assistant (VLAN 20)" and ha20["twin_of"] == "10.40.1.100" and "twin_of" not in mem[saved["10.40.1.100"]["id"]]
# the twin name is never replaced by an automatic one; a name chosen by hand on a twin stays
from app.recognition import naming  # noqa: E402
assert not naming.is_better(after["10.40.20.100"], "mdns", "esphome-builder-1a2b3c4d")
devices_config.update_device(saved["10.40.20.1"]["id"], "Router VLAN")
asyncio.run(fake.name_twins())
assert {d["ip"]: d for d in devices_config.load_devices()}["10.40.20.1"]["name"] == "Router VLAN"
# no longer a twin (the host lost its VLAN address): the name goes back to the address, the next check names it again
host.discard("10.40.20.100")
asyncio.run(fake.name_twins())
assert {d["ip"]: d for d in devices_config.load_devices()}["10.40.20.100"]["name"] == "Home Assistant (VLAN 20)"     # offline: it cannot tell, it keeps it
mem[saved["10.40.20.100"]["id"]] = {**mem[saved["10.40.20.100"]["id"]], "online": True}
asyncio.run(fake.name_twins())
back = {d["ip"]: d for d in devices_config.load_devices()}["10.40.20.100"]
ha20 = mem[saved["10.40.20.100"]["id"]]
assert back["name"] == "10.40.20.100" and "name_source" not in back and "twin_of" not in ha20 and ha20["name"] == "10.40.20.100", (back, ha20)

# the old card of a laptop that moved from VLAN 20 to the main network (offline, its last MAC = the new card's) is not a twin (18/11 review)
fake2 = Fake()
fake2.devices = {"new": {"id": "new", "ip": "10.40.1.60", "mac": "AA:00:00:00:00:60", "name": "Laptop", "online": True},
                 "old": {"id": "old", "ip": "10.40.20.60", "mac": None, "name": "Laptop", "online": False}}
fake2._last_mac = {"old": "AA:00:00:00:00:60"}
fake2._twin_of = {}
assert twins.find([{**c, "mac": c["mac"] or fake2._last_mac.get(c["id"])} for c in fake2.devices.values()], set(), None, frozenset(), scope.network_of) == {"old": "new"}
devices_config.add_devices([{"ip": "10.40.1.60", "name": "Laptop"}, {"ip": "10.40.20.60", "name": "Laptop"}])
ids = {d["ip"]: d["id"] for d in devices_config.load_devices()}
fake2.devices = {ids["10.40.1.60"]: {**fake2.devices["new"], "id": ids["10.40.1.60"]}, ids["10.40.20.60"]: {**fake2.devices["old"], "id": ids["10.40.20.60"]}}
fake2._last_mac = {ids["10.40.20.60"]: "AA:00:00:00:00:60"}
asyncio.run(fake2.name_twins())
assert fake2._twin_of == {} and {d["ip"]: d for d in devices_config.load_devices()}["10.40.20.60"]["name"] == "Laptop", fake2._twin_of
# a long name keeps the network readable and is never longer than a card name may be (the probe would cut it and the twin be written every cycle)
from app.formatters import MAX_NAME_LEN, truncate_name  # noqa: E402
long = twins.name("Home Assistant Green nel quadro del corridoio", named)
assert len(long) <= MAX_NAME_LEN and long.endswith("(IoT)") and truncate_name(long) == long, long

# a restart with the main router off: nothing known yet, the twin answers on the VLAN: the main card's last MAC still pairs them (18/11 review 3)
fake3 = Fake()
fake3.devices = {k: dict(v) for k, v in mem.items()}
r1, r20 = saved["10.40.1.1"]["id"], saved["10.40.20.1"]["id"]
fake3.devices[r1].update(mac=None, online=False)
fake3.devices[r20].update(mac=R_MAC, online=True)
fake3._last_mac, fake3._twin_of = {r1: R_MAC}, {}
asyncio.run(fake3.name_twins())
assert fake3._twin_of.get(r20) == "10.40.1.1", fake3._twin_of
# a twin off for more than a day (its address on the VLAN was removed): the pair ends, the card keeps its name but no longer sits beside the main one
import time as _time  # noqa: E402
fake3.devices[r1].update(mac=R_MAC, online=True)
fake3.devices[r20].update(mac=None, online=False, last_seen=_time.time() - 2 * 86400)
fake3._last_mac[r20] = R_MAC
asyncio.run(fake3.name_twins())
assert r20 not in fake3._twin_of and "twin_of" not in fake3.devices[r20], fake3._twin_of
# a name with no origin that is not a placeholder (written in devices.yaml by hand, or a card added from a search) is presumed chosen by hand,
# as naming.is_better says: never taken by the twin name, so never lost when the pair ends (19/11 review 4)
devices_config.add_devices([{"ip": "10.40.20.77", "name": "Switch cantina"}])
hand = {d["ip"]: d for d in devices_config.load_devices()}["10.40.20.77"]
assert "name_source" not in hand, hand
assert not devices_config.set_twin_name(hand["id"], "Gateway-1 (VLAN 20)")
assert {d["ip"]: d for d in devices_config.load_devices()}["10.40.20.77"]["name"] == "Switch cantina"
devices_config.add_devices([{"ip": "10.40.20.78", "name": "android-7f3a9c2b"}])       # a placeholder with no origin: an automatic name, it may go
ph = {d["ip"]: d for d in devices_config.load_devices()}["10.40.20.78"]
assert devices_config.set_twin_name(ph["id"], "Gateway-1 (VLAN 20)")
print("ALL OK")
