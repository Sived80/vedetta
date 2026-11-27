# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The judge of the functions of a network (networks/caps.py), for the panel «Networks»: for each of the 7 functions, from the facts it is handed,
on (with its source and how), off (a switch the person turned off), how to switch it on (the ways, as data with text keys), or coming soon.
1) the main network: everything from Vedetta, ports and model always on with no switch (decision «A» of 13/11), the strays coming soon; 2) a network reached through a second
interface of Home Assistant: as the main one, the switches follow `touch` and can be changed; 3) a network behind the router with nothing
more: presence by ping, everything else is a way to switch it on; 4) the same network with the router's DNS, a router integration in Home
Assistant, mDNS announcements and answers: names, MACs, stealth, ports and model on, each from its source; 5) the shape of every answer over
every combination of facts: known states, sources and keys, one recommended way per list, a switch only on ports and model, nothing but data
(text keys, never sentences), and every text key listed by text_keys() (keys of the page: "js."); 6) the module is pure.
Invented private addresses only (10.x and 192.168.50-99.x).
    python tests/check_networks_caps.py"""
import ast
import itertools
import json
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()          # nothing is written, but the log must never go to the real data folder
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.networks import caps  # noqa: E402

FUNCS = ("pres", "name", "mac", "port", "deep", "quiet", "stray")
assert caps.FUNCS == FUNCS


def judge(**facts):
    base = {"direct": False, "main": False, "touch": "presence", "cidr": "192.168.60.0/24", "ha_ip": "192.168.50.2", "iface": "enp0s18"}
    got = caps.judge(caps.Facts(**{**base, **facts}))
    assert tuple(got) == FUNCS, got
    return got


def on(source, by, **more):
    return {"state": "on", "source": source, "by": by, **more}


def switch(is_on, touch_on, touch_off):
    return {"on": is_on, "touch_on": touch_on, "touch_off": touch_off}



# 1) the main network
main = judge(direct=True, main=True, touch="full", cidr="192.168.50.0/24")
assert main["pres"] == on("ved", "arp") and main["mac"] == on("ved", "arp") and main["quiet"] == on("ved", "arp"), main
assert main["name"] == on("ved", "mdns_netbios"), main["name"]
assert main["port"] == on("ved", "port_probe"), main["port"]
assert main["deep"] == on("ved", "upnp_mdns"), main["deep"]
assert judge(direct=True, main=True, touch="presence")["port"] == on("ved", "port_probe"), "the main network: always on, whatever touch says"
assert main["stray"] == {"state": "soon"}

# 2) a second interface of Home Assistant: the switches follow touch
lab = judge(direct=True, touch="ports", cidr="10.20.0.0/24")
assert lab["port"] == on("ved", "port_probe", switch=switch(True, "ports", "presence")), lab["port"]
assert lab["deep"] == {"state": "off", "source": "ved", "by": "upnp_mdns", "switch": switch(False, "full", "ports")}, lab["deep"]
low = judge(direct=True, touch="presence", cidr="10.20.0.0/24")
assert low["port"]["state"] == "off" and low["port"]["switch"]["on"] is False and low["deep"]["state"] == "off"
assert judge(direct=True, touch="full", cidr="10.20.0.0/24")["deep"] == on("ved", "upnp_mdns", switch=switch(True, "full", "ports"))
assert low["pres"] == on("ved", "arp") and low["stray"] == {"state": "soon"}

# 3) behind the router, nothing more
bare = judge(vlan=60)
assert bare["pres"] == on("ved", "ping"), bare["pres"]
assert bare["port"] == {"state": "off", "source": "ved", "by": "through_router", "switch": switch(False, "ports", "presence")}, bare["port"]
assert bare["deep"] == bare["port"], "behind the router the model follows the switch of the ports (B, 14/11)"
# Vedetta listens to ARP on the main interface only (20/11): what only Home Assistant inside the network would give is "coming", on every
# network behind the router; «Home Assistant inside» is still shown for MAC, marked as coming, with the ways that work today.
ids = {k: [w["id"] for w in bare[k]["ways"]] for k in ("name", "mac")}
assert ids == {"name": ["router_dns", "router_integration"], "mac": ["router_integration", "snmp", "ha_inside"]}, ids
assert bare["quiet"] == {"state": "soon"} and bare["stray"] == {"state": "soon"}, (bare["quiet"], bare["stray"])
assert bare["mac"]["need"] == "one"
snmp = bare["mac"]["ways"][1]
assert snmp["soon"] is False and snmp["best"] is False and snmp["by"] == "router", snmp      # no longer «coming soon»: the page has its form
assert judge(vlan=60, snmp=True)["mac"] == on("router", "snmp"), "the router's ARP table gave MACs of the network: MAC on, from the router"
inside = bare["mac"]["ways"][2]
assert inside["by"] == "ha" and inside["soon"] is True and inside["best"] is False and inside["where"] == ["ha.settings", "ha.system", "ha.network"], inside
assert inside["params"] == {"cidr": "192.168.60.0/24", "vlan": 60,
                            "example": "ha network vlan enp0s18 60 --ipv4-method static --ipv4-address 192.168.60.100/24"}, inside["params"]
assert "example" not in judge()["mac"]["ways"][2]["params"], "no VLAN number: no example command"
assert judge(vlan=7, cidr="192.168.60.16/28")["mac"]["ways"][2]["params"]["example"].endswith("192.168.60.30/28"), "a small network: the last usable address"
asked = judge(touch="ports")
assert asked["deep"] == asked["port"], "asked, no answer: the firewall stops the model too"
assert judge(touch="ports", answers=True)["deep"] == on("ved", "through_router", switch=switch(True, "ports", "presence")), "the model from the search through the router"
assert asked["port"] == {"state": "how", "need": "this", "switch": switch(True, "ports", "presence"),
                         "ways": [{"id": "firewall_rule", "by": "router", "best": True, "soon": False, "where": ["router.firewall", "router.rules"],
                                   "params": {"from": "192.168.50.2", "to": "192.168.60.0/24"}}]}, asked["port"]

# 4) behind the router, with every help
full = judge(touch="ports", answers=True, dns_names=True, trackers=True, mdns=True)
assert full["name"] == on("router", "router_dns") and full["mac"] == on("ha", "router_integration") and full["quiet"] == on("ha", "router_integration")
assert full["port"] == on("ved", "through_router", switch=switch(True, "ports", "presence")), full["port"]
assert full["deep"] == on("router", "mdns_reflector"), full["deep"]
assert full["stray"] == {"state": "soon"} and full["pres"] == on("ved", "ping")
assert judge(trackers=True)["name"] == on("ha", "router_integration"), "no DNS names: the names of the router integration"

# 5) the shape of every answer
KEYS = set(caps.text_keys())
STATES = {"on", "off", "how", "soon"}
seen_states = set()
for direct, is_main, touch, answers, dns, trackers, mdns, vlan in itertools.product((False, True), (False, True), caps.TOUCH, *[(False, True)] * 4, (None, 60)):
    if is_main and not direct:
        continue
    got = judge(direct=direct, main=is_main, touch=touch, answers=answers, dns_names=dns, trackers=trackers, mdns=mdns, vlan=vlan)
    json.dumps(got)                                   # data only
    for func, cap in got.items():
        seen_states.add(cap["state"])
        assert cap["state"] in STATES, cap
        assert ("switch" in cap) <= (func in ("port", "deep")), (func, cap)
        assert func != "pres" or cap["state"] == "on", "presence is always on"
        if cap["state"] in ("on", "off"):
            assert cap["source"] in caps.SOURCES and "js.networks.by." + cap["by"] in KEYS, cap
        if cap["state"] == "how":
            assert cap["ways"] and cap["need"] == ("this" if len(cap["ways"]) == 1 else "one"), cap
            assert sum(w["best"] for w in cap["ways"]) == 1, cap
            assert "js.networks.how.%s.lead" % func in KEYS, func
            for way in cap["ways"]:
                assert way["by"] in ("ha", "router") and all("js.networks.way.%s.%s" % (way["id"], part) in KEYS for part in ("title", "what", "sec")), way
                assert all(crumb == "net" or "js.networks.where." + crumb in KEYS for crumb in way["where"]), way
        if "switch" in cap:
            sw = cap["switch"]
            assert not is_main and sw["on"] is (cap["state"] in ("on", "how")), (func, cap)
            assert caps.TOUCH.index(sw["touch_on"]) > caps.TOUCH.index(sw["touch_off"]), sw
assert seen_states == STATES, seen_states
assert all(k.startswith("js.networks.") for k in KEYS) and len(KEYS) == len(caps.text_keys())

# 6) pure: no import but the standard library
tree = ast.parse(open(caps.__file__, encoding="utf-8").read())
imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
imported |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.level == 0}
assert imported <= {"dataclasses", "ipaddress"}, imported
assert not [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.level and n.module != "model"], "only the model of the package"
print("check_networks_caps: ok")
