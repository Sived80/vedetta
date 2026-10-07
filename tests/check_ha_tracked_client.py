"""A device that a router integration only tracks (device_tracker) is not a router; the router itself is.
Real case: Shelly Pro 4PM relays tracked by the MikroTik integration were read as routers (tie with IoT, group "Other")."""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import ha_data, ha_registry

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
other = {"id": "e", "ip": "10.0.0.3", "name": "Cam", "extra": {}, "ha_registry": card(["onvif"], ["camera"])}
assert ha_data.type_scores(other).get("media", 0) >= ha_data.W_DECLARED, ha_data.type_scores(other)
tracked = dict(other, ha_registry=card(["onvif"], ["device_tracker"]))
assert ha_data.type_scores(tracked).get("media", 0) < ha_data.W_DECLARED, ha_data.type_scores(tracked)   # any integration, any group
# Integration not in the table: what HA does with the device still says something
unknown_iot = {"id": "f", "ip": "10.0.0.4", "name": "AC", "extra": {}, "ha_registry": card(["some_new_integration"], ["device_tracker", "climate", "sensor"])}
assert ha_data.infer_type(unknown_iot) == "iot", ha_data.type_scores(unknown_iot)
unknown_player = {"id": "g", "ip": "10.0.0.5", "name": "Box", "extra": {}, "ha_registry": card(["some_new_integration"], ["media_player"])}
assert ha_data.infer_type(unknown_player) == "media", ha_data.type_scores(unknown_player)
unknown_tracker = {"id": "h", "ip": "10.0.0.6", "name": "Box", "extra": {}, "ha_registry": card(["some_new_integration"], ["device_tracker"])}
assert ha_data.infer_type(unknown_tracker) == "generic", ha_data.type_scores(unknown_tracker)

# A declared model beats the banner of a port (real case: two cameras read as routers because of a wrong banner on a HomeKit port)
cam = {"id": "i", "ip": "10.0.0.7", "name": "Camera-1", "brand": "Lumi United", "extra": {"mdns_model": "lumi.camera.acn007", "mdns_services": "_hap._tcp"},
       "scanned_ports": [{"label": "49152 · IKEA Tradfri zigbee controller httpd", "confirmed": False}]}
assert ha_data.infer_type(cam) == "media", ha_data.type_scores(cam)
room = {"id": "j", "ip": "10.0.0.8", "name": "Camera da letto", "extra": {}}                  # the room is not a camera
assert ha_data.infer_type(room) != "media", ha_data.type_scores(room)
speaker = {"id": "k", "ip": "10.0.0.9", "name": "Box", "extra": {"mdns_model": "HomePod"}, "scanned_ports": [{"label": "7000 · rtsp", "confirmed": False}]}
assert ha_data.infer_type(speaker) == "audio", ha_data.type_scores(speaker)
print("TUTTO OK")
