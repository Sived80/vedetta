# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""Twin cards by the same TLS certificate (1.0.1): a router with an address on the main network and one on each VLAN reached only through it
(no MAC there) presents the same certificate on every address. The card on the main network is the main one, every card of the group on
another network is its twin (more than two addresses too). A certificate shared by two cards of ONE network says nothing (two devices of
one maker with its default certificate): ignored. A MAC twin wins over a certificate twin; no card on the main network, no twins.
    python tests/check_twins_cert.py"""
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

MAIN = Network("main", ipaddress.ip_network("10.70.0.0/24"), frozenset({"direct"}), "full", "confirmed")
V20 = Network("lab20", ipaddress.ip_network("10.70.20.0/24"), frozenset({"router"}), "presence", "confirmed", vlan=20)
V30 = Network("lab30", ipaddress.ip_network("10.70.30.0/24"), frozenset({"router"}), "presence", "confirmed", vlan=30)
scope = Scope((MAIN, V20, V30))
FP = "3f" * 32
CAM = "a1" * 32
R_MAC = "02:5A:77:00:00:01"


def find(cards):
    return twins.find(cards, set(), None, frozenset(), scope.network_of)


router = [{"id": "r0", "ip": "10.70.0.1", "mac": R_MAC, "tls_fp": FP}, {"id": "r20", "ip": "10.70.20.1", "mac": None, "tls_fp": FP},
          {"id": "r30", "ip": "10.70.30.1", "mac": None, "tls_fp": FP.upper()}]
assert find(router) == {"r20": "r0", "r30": "r0"}, find(router)                                  # three addresses, one machine
assert find(router[1:]) == {}                                                                    # no card on the main network
# two cameras of one maker on the main network with its default certificate, a third on a VLAN: nobody is a twin
cams = [{"id": "c1", "ip": "10.70.0.21", "mac": "02:5A:77:00:00:21", "tls_fp": CAM}, {"id": "c2", "ip": "10.70.0.22", "mac": "02:5A:77:00:00:22", "tls_fp": CAM},
        {"id": "c3", "ip": "10.70.30.23", "mac": None, "tls_fp": CAM}]
assert find(cams) == {}, find(cams)
two_on_vlan = [cams[0], {**cams[1], "ip": "10.70.30.22"}, cams[2]]
assert find(two_on_vlan) == {}, find(two_on_vlan)                                                # two of the group on one VLAN: same rule
assert find(router + cams) == {"r20": "r0", "r30": "r0"}
# a MAC twin wins: the card has the MAC of one machine and the certificate of another
other = {"id": "o0", "ip": "10.70.0.2", "mac": "02:5A:77:00:00:02", "tls_fp": "b2" * 32}
mixed = router + [other, {"id": "o20", "ip": "10.70.20.2", "mac": "02:5A:77:00:00:02", "tls_fp": FP}]
assert find(mixed)["o20"] == "o0", find(mixed)
# an address in no network, an empty fingerprint: nothing
assert find([router[0], {"id": "x", "ip": "10.9.0.1", "mac": None, "tls_fp": FP}]) == {}
assert find([{**router[0], "tls_fp": None}, {**router[1], "tls_fp": None}]) == {}

# --- the step at the end of the cycle: the fingerprint comes from the card's saved scan
from app.storage import devices_config  # noqa: E402
from app import identity_upkeep  # noqa: E402

devices_config.add_devices([{"ip": c["ip"], "name": c["ip"]} for c in router])
saved = {d["ip"]: d for d in devices_config.load_devices()}
devices_config.update_auto_name(saved["10.70.0.1"]["id"], "Gateway-7", "mdns")
for c in router:
    devices_config.update_scan_info(saved[c["ip"]]["id"], {"tls_fp": c["tls_fp"], "scanned_at": 1})
mem = {saved[c["ip"]]["id"]: {"id": saved[c["ip"]]["id"], "ip": c["ip"], "mac": c["mac"], "online": True,
                              "name": "Gateway-7" if c["ip"] == "10.70.0.1" else c["ip"]} for c in router}


class Fake(identity_upkeep.IdentityUpkeep):
    devices = mem
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
fake = Fake()
asyncio.run(fake.name_twins())
after = {d["ip"]: d for d in devices_config.load_devices()}
assert fake._twin_of == {saved["10.70.20.1"]["id"]: "10.70.0.1", saved["10.70.30.1"]["id"]: "10.70.0.1"}, fake._twin_of
assert after["10.70.20.1"]["name"] == "Gateway-7 (VLAN 20)" and after["10.70.30.1"]["name"] == "Gateway-7 (VLAN 30)", after
print("check_twins_cert: ok")
