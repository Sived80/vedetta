"""A network behind the router in which Home Assistant already has an interface (a VLAN the person shared with HA, 20/11): the panel
«Networks» must not tell the person to do what is done ("put Home Assistant inside the network"). Vedetta does not use that interface yet
(it listens to ARP on the main one only), so what it would give is "coming": Hidden and Strays say so; MAC keeps its other ways (router
integration, SNMP) without that one. Without such an interface everything is as before. Invented private addresses only.
    python tests/check_caps_ha_leg.py"""
import ipaddress
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.networks import caps, host_read, panel  # noqa: E402
from app.networks.model import Network  # noqa: E402

failed = 0


def check(cond, msg):
    global failed
    print(("ok: " if cond else "FAILED: ") + msg)
    failed += 0 if cond else 1


def ways(cap):
    return [w["id"] for w in cap.get("ways") or []]


host = {"interfaces": [{"name": "eth0", "ipv4": [{"address": "10.60.0.5", "prefix": 24}]},
                       {"name": "eth0.20", "vlan": {"id": 20, "parent": "eth0"}, "ipv4": [{"address": "10.61.0.100", "prefix": 24}]}]}
net = Network("iot", ipaddress.ip_network("10.61.0.0/24"), frozenset({"routed"}), "ports", "confirmed", name="IoT", vlan=20)
other = Network("cam", ipaddress.ip_network("10.62.0.0/24"), frozenset({"routed"}), "ports", "confirmed", name="Cam", vlan=30)
check(host_read.has_leg(net.cidr, host) and not host_read.has_leg(other.cidr, host), "the host has a leg in 10.61.0.0/24, not in 10.62.0.0/24")


def judge(network):
    seen = panel.Seen(cards=(), last={}, host=host, trackers=(), mdns=(), own_ip="10.60.0.5", iface="eth0", now=0.0)
    return panel.describe(network, seen, network.name, False)["caps"]


got = judge(net)
check(got["quiet"]["state"] == "soon" and got["stray"]["state"] == "soon", "Hidden and Strays: coming, not «how to turn it on»: %s %s" % (got["quiet"], got["stray"]))
check(all("ha_inside" not in ways(c) for c in got.values()), "no function proposes to put Home Assistant inside the network")
check(got["mac"]["state"] == "how" and ways(got["mac"]) == ["router_integration", "snmp"], "MAC keeps its other ways: %s" % ways(got["mac"]))
before = judge(other)
check(before["quiet"]["state"] == "soon" and before["stray"]["state"] == "soon", "without a leg (VLAN 30): Hidden and Strays are coming too, the same")
inside = [w for w in before["mac"].get("ways") or [] if w["id"] == "ha_inside"]
check(len(inside) == 1 and inside[0]["soon"] is True, "and «Home Assistant inside» is offered for MAC only as «coming»: %s" % inside)
print("ALL OK" if not failed else f"{failed} FAILED")
sys.exit(1 if failed else 0)
