# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""1.0.4: the page has the ten groups Home Assistant sees (router, server, pc, phone, media, audio, iot, printer, camera, generic); inside
the smart home group ("iot") each card has a family (lights, climate, security...), worked out from its finer kind (data/device_kinds.json)
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
assert ha_data.compact_device(probe)["family"] == "climate", ha_data.effective_kind(probe)     # as in the climate view of Home Assistant
assert ha_data.compact_device(module)["family"] == "other"                # a smart home module with no finer kind: other devices
card = ha_data.compact_device(router)
assert card["type"] == "router" and card["family"] is None, card           # a family only inside the smart home group
print("ok: a boiler is smart home on the page, family climate")

# the families come from the table of kinds, in one place
# the summaries of the Home dashboard of Home Assistant (lights, climate, security, energy), gates and doors apart (27/11), then appliances and other devices
assert device_groups.FAMILIES == ("lights", "climate", "security", "access", "energy", "appliance", "other"), device_groups.FAMILIES
assert device_groups.family_of("light", "iot") == "lights" and device_groups.family_of("plug", "iot") == "lights"
assert device_groups.family_of("humidity", "iot") == "climate" and device_groups.family_of("temperature", "iot") == "climate"
assert device_groups.family_of("airquality", "iot") == "other"          # not in the climate view of Home Assistant
# covers: blinds, curtains and awnings in climate, garage doors and gates in their own family, access (27/11) (the cover device classes of Home Assistant)
assert [device_groups.family_of(k, "cover") for k in ("blinds", "curtain", "awning")] == ["climate"] * 3
assert [device_groups.family_of(k, "cover") for k in ("garage", "gate")] == ["access"] * 2
assert device_groups.family_of("inverter", "energy") == "energy" and device_groups.family_of("washer", "appliance") == "appliance"
assert device_groups.family_of("pump", "water") == "other" and device_groups.family_of("bluetooth", "iot") == "other"
assert device_groups.family_of("hub", "iot") == "other" and device_groups.family_of("microcontroller", "iot") == "other"
assert device_groups.family_of(None, None) == "other" and device_groups.family_of("brandnew", "iot") == "other"
assert device_groups.family_of("brandnew", "cover") == "climate"          # a cover with no class is in the climate view of Home Assistant
assert all(device_groups.family_of(k["id"], k["group"]) in device_groups.FAMILIES for k in ha_data._read_kind_rows())
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
assert ha_data.effective_family(router, {"type_user": "iot"}) == "other"
# a type saved by the debug build with 16 groups: smart home, and its family
old = ha_data.compact_device(washer, {"type_user": "climate"})
assert old["type"] == "iot" and old["family"] == "climate", old
assert ha_data.device_facts(washer, {"type_user": "climate"})["type"] == "iot"
print("ok: the family chosen by hand")

# a family saved before the six families of 1.0.4: sensors -> climate, hubs and water -> other; cover -> the climate or access family
# its kind says (a blind stays in climate, a gate goes to access), climate when the kind says neither
blind = {"id": "c1", "ip": "192.0.2.45", "name": "Tapparella sala", "mac": "02:00:00:00:00:45", "online": True, "extra": {}}
gate = {"id": "g1", "ip": "192.0.2.46", "name": "Cancello", "mac": "02:00:00:00:00:46", "online": True, "extra": {}}
for saved, device, family in (("sensors", washer, "climate"), ("hubs", boiler, "other"), ("water", boiler, "other"), ("cover", blind, "climate"),
                              ("cover", gate, "access"), ("cover", washer, "climate")):
    card = ha_data.compact_device(device, {"family_user": saved})
    assert (card["family"], card["family_user"]) == (family, family), (saved, device["name"], card["family"], card["family_user"])
    assert ha_data.compact_device(device, {"type_user": saved})["family"] == family, (saved, device["name"])   # a type of the debug build with 16 groups
assert ha_data.compact_device(boiler, {"family_user": "toaster"})["family_user"] is None
print("ok: a family saved before 1.0.4 finds its place")
