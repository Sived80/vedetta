"""A device that a router integration only tracks (device_tracker) is not a router; the router itself is.
Real case: Shelly Pro 4PM relays tracked by the MikroTik integration were read as routers (tie with IoT, group "Other")."""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import ha_data, ha_registry

def card(domains, ents):
    return {"name": "x", "domains": domains, "entity_domains": ents}

shelly = {"id": "a", "ip": "10.0.0.120", "name": "Shelly-2", "brand": "Shelly", "vendor": "Espressif", "vendor_role": "component",
          "extra": {"mdns": "shellypro4pm-083af2000039", "mdns_services": "_http._tcp, _shelly._tcp", "ha_integration": "mikrotik_router, shelly"},
          "ha_registry": card(["mikrotik_router", "shelly"], ["device_tracker", "switch"])}
assert ha_data.infer_type(shelly, "shelly") == "iot", ha_data.type_scores(shelly, "shelly")
assert ha_data.infer_type(shelly, None) == "iot", ha_data.type_scores(shelly, None)

phone = {"id": "b", "ip": "10.0.0.50", "name": "Client", "extra": {"ha_integration": "unifi"}, "ha_registry": card(["unifi"], ["device_tracker"])}
assert "router" not in ha_data.type_scores(phone), ha_data.type_scores(phone)
hub = {"id": "c", "ip": "10.0.0.1", "name": "Gateway", "extra": {}, "ha_registry": card(["unifi"], ["device_tracker", "sensor", "switch"])}
assert ha_data.type_scores(hub).get("router", 0) >= ha_data.W_DECLARED, ha_data.type_scores(hub)
old = {"id": "d", "ip": "10.0.0.2", "name": "Gateway", "extra": {}, "ha_registry": {"name": "x", "domains": ["unifi"]}}   # registry saved before the key existed
assert ha_data.type_scores(old).get("router", 0) >= ha_data.W_DECLARED

idx = ha_registry.build_index(
    [{"id": "D1", "connections": [["mac", "08:3a:f2:00:00:05"]], "config_entries": ["E1"]}],
    [{"entity_id": "device_tracker.shelly", "device_id": "D1"}, {"entity_id": "switch.relay", "device_id": "D1"}],
    [], [{"entry_id": "E1", "domain": "mikrotik_router", "title": "T"}])
assert idx["by_mac"]["08:3a:f2:00:00:05"]["entity_domains"] == ["device_tracker", "switch"]
print("TUTTO OK")
