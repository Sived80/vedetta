"""The router of the house is a router (18/11): the address of the default route, and another address with the same MAC (the router on a VLAN
behind it, its MAC read from its own table). Before, a gateway running a controller (UniFi: Tomcat, nginx, SSH) scored 13 against 7 for server,
certainty 46, and its address on the VLAN tied router 3 / server 3: both stayed under analysis for days."""
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.recognition import roles  # noqa: E402
from app.ha import ha_type_evidence as T  # noqa: E402

roles._rt.roles = {"by_ip": {"192.168.1.1": {"gateway": "route", "dns": "dns"}}, "via": {}, "names": {}, "types": {}, "dhcp": [],
                   "gateway_mac": "02:5A:11:11:22:33"}
assert roles.is_gateway("192.168.1.1", None)
assert roles.is_gateway("192.168.20.1", "02-5a-11-11-22-33")                 # the same router on the VLAN, any spelling of the MAC
assert not roles.is_gateway("192.168.20.5", "02:5A:11:11:22:34") and not roles.is_gateway("192.168.20.5", None)
roles._rt.roles = {**roles._rt.roles, "gateway_mac": None}
assert not roles.is_gateway("192.168.20.1", None)                            # no MAC of the gateway known: nobody is its twin

roles._rt.roles = {**roles._rt.roles, "gateway_mac": "02:5A:11:11:22:33"}
twin = {"ip": "192.168.20.1", "mac": "02:5A:11:11:22:33", "name": "192.168.20.1", "extra": {}}
ev = T.type_evidence(twin, "generic", None)
assert any(e["family"] == "gateway" and e["group"] == "router" for e in ev), ev
other = {"ip": "192.168.20.7", "mac": "02:5A:11:11:22:99", "name": "192.168.20.7", "extra": {}}
assert not any(e["family"] == "gateway" for e in T.type_evidence(other, "generic", None))
print("ALL OK")
