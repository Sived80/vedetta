# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""A router's own address on a network behind it (the gateway of a VLAN) is found as the twin of the router's card by its TLS certificate or by
SNMP, with no MAC (the VLAN is reached through the router). It must be a "router" like its main card, not the "server" its open ports suggest:
the role of the house's router was told by the default route or its MAC only. A twin of any other card keeps its own type. Invented values."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import ha_data  # noqa: E402
from app.recognition import roles  # noqa: E402

ROUTER = "192.0.2.1"
roles.roles_for = lambda ip: ["gateway"] if ip == ROUTER else []
roles.upnp_types = lambda ip: []
PORTS = [{"label": f"{n} · {s}", "confirmed": True} for n, s in ((22, "ssh"), (80, "http"), (443, "https"), (8443, "https-alt"))]


def card(ip, **more):
    return {"id": "c-" + ip, "ip": ip, "name": ip, "mac": None, "extra": {"http_server": "nginx", "title": "Login"}, "scanned_ports": PORTS,
            "is_mobile": False, **more}


alone = ha_data.infer_type(card("10.30.0.1"))
assert alone != "router", ("the fixture must look like something else on its own", alone)

# the twin of the router's card (twin_of = the main card's address): a router
assert ha_data.infer_type(card("10.30.0.1", twin_of=ROUTER)) == "router", ha_data.type_scores(card("10.30.0.1", twin_of=ROUTER))

# the twin of a card that is not the router keeps its own type
assert ha_data.infer_type(card("10.30.0.5", twin_of="192.0.2.50")) == alone

# a type chosen by hand still wins
assert ha_data.effective_type(card("10.30.0.1", twin_of=ROUTER), {"type_user": "server"}) == "server"

print("OK twin router type")
