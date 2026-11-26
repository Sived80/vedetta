"""1.0.4: the page has the ten groups Home Assistant sees (router, server, pc, phone, media, audio, iot, printer, camera, generic); inside
the smart home group ("iot") each card has a family (lights, sensors, climate...), worked out from its finer kind (data/device_kinds.json)
in one place (device_groups). Home Assistant keeps seeing "iot" (MQTT attribute and model "type", events "type"): the automations and the
blueprints written before keep working. A family can be chosen by hand (family_user); a type "climate" saved by an earlier debug build is
read as iot with the family climate. Invented values only."""
import json
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import device_groups
from app.ha import ha_data, ha_notify, mqtt_payloads

boiler = {"id": "b1", "ip": "192.0.2.40", "name": "Caldaia", "mac": "02:00:00:00:00:40", "online": True, "extra": {}}
washer = {"id": "w1", "ip": "192.0.2.41", "name": "Lavatrice", "mac": "02:00:00:00:00:41", "online": True, "extra": {}}
plug = {"id": "p1", "ip": "192.0.2.42", "name": "Presa smart plug", "mac": "02:00:00:00:00:42", "online": True, "extra": {}}
probe = {"id": "t1", "ip": "192.0.2.43", "name": "Sensore temperatura", "mac": "02:00:00:00:00:43", "online": True, "extra": {}}
module = {"id": "m1", "ip": "192.0.2.44", "name": "Shelly1", "mac": "02:00:00:00:00:44", "online": True, "extra": {"api_source": "shelly"}}
router = {"id": "r1", "ip": "192.0.2.1", "name": "Router", "mac": "02:00:00:00:00:01", "online": True, "extra": {}, "brand": "Netgear"}

# ten groups, as Home Assistant knows them
assert device_groups.TYPE_ORDER == ("router", "server", "pc", "phone", "media", "audio", "iot", "printer", "camera", "generic"), device_groups.TYPE_ORDER
assert ha_data.TYPE_ORDER == device_groups.TYPE_ORDER

# the page: a boiler is in the smart home group, family climate
assert ha_data.infer_type(boiler) == "iot", ha_data.type_scores(boiler)
card = ha_data.compact_device(boiler)
assert card["type"] == "iot" and card["family"] == "climate" and card["icon"] == "water-boiler" and card["family_user"] is None, card
assert ha_data.compact_device(washer)["family"] == "appliance"
assert ha_data.compact_device(plug)["family"] == "lights"
assert ha_data.compact_device(probe)["family"] == "sensors", ha_data.effective_kind(probe)
assert ha_data.compact_device(module)["family"] == "hubs"                 # a smart home module with no finer kind: hubs and modules
card = ha_data.compact_device(router)
assert card["type"] == "router" and card["family"] is None, card           # a family only inside the smart home group
print("ok: a boiler is smart home on the page, family climate")

# the families come from the table of kinds, in one place
assert device_groups.FAMILIES == ("lights", "sensors", "climate", "appliance", "energy", "security", "cover", "water", "hubs"), device_groups.FAMILIES
assert device_groups.family_of("light", "iot") == "lights" and device_groups.family_of("humidity", "iot") == "sensors"
assert device_groups.family_of("pump", "water") == "water" and device_groups.family_of("bluetooth", "iot") == "hubs"
assert device_groups.family_of(None, None) == "hubs" and device_groups.family_of("brandnew", "iot") == "hubs"
print("ok: the families come from the kinds")

# Home Assistant: the same group as before
facts = ha_data.device_facts(boiler)
assert facts["type"] == "iot" and facts["kind"] == "boiler", facts
data = ha_notify.event_data({"kind": "new", "card": "b1", "params": {"label": "Caldaia", "ip": "192.0.2.40", **facts}})
assert data["type"] == "iot" and data["kind"] == "boiler", data
desired = mqtt_payloads.build_desired({"b1": boiler}, {"b1": "iot"}, 0, set(), None, {"b1": "boiler"})
attrs = [json.loads(v) for k, v in desired.items() if k.endswith("/attrs")]
assert attrs and attrs[0]["type"] == "iot" and attrs[0]["kind"] == "boiler", desired
configs = [json.loads(v) for k, v in desired.items() if k.endswith("vedetta_b1/config")]
assert configs and all(c["dev"]["model"] == "iot" for c in configs), configs
print("ok: Home Assistant sees iot")

# a family chosen by hand: kept when it is known and the card is smart home, else ignored
assert ha_data.compact_device(boiler, {"family_user": "security"})["family"] == "security"
assert ha_data.compact_device(boiler, {"family_user": "security"})["family_user"] == "security"
assert ha_data.compact_device(boiler, {"family_user": "toaster"})["family"] == "climate"
assert ha_data.compact_device(boiler, {"type_user": "media", "family_user": "security"})["family"] is None
assert ha_data.effective_family(router, {"type_user": "iot"}) == "hubs"
# a type saved by the debug build with 16 groups: smart home, and its family
old = ha_data.compact_device(washer, {"type_user": "climate"})
assert old["type"] == "iot" and old["family"] == "climate", old
assert ha_data.device_facts(washer, {"type_user": "climate"})["type"] == "iot"
print("ok: the family chosen by hand")
