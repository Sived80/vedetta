"""1.0.4: the smart home kinds have their own groups on the page (climate, appliance, energy, security, cover, water), but Home Assistant
sees the group of before ("iot") in the MQTT attribute "type", in the model of the MQTT device and in the "type" of the events: the
automations and the blueprints written for 1.0.3 keep working. A type chosen by hand among the new groups is kept; an old "iot" too."""
import json
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import device_groups
from app.analysis import status
from app.ha import ha_data, ha_notify, mqtt_payloads
from app.recognition import evidence

boiler = {"id": "b1", "ip": "192.0.2.40", "name": "Caldaia", "mac": "02:00:00:00:00:40", "online": True, "extra": {}}
washer = {"id": "w1", "ip": "192.0.2.41", "name": "Lavatrice", "mac": "02:00:00:00:00:41", "online": True, "extra": {}}
plug = {"id": "p1", "ip": "192.0.2.42", "name": "Presa smart plug", "mac": "02:00:00:00:00:42", "online": True, "extra": {}}

# the page: the group of the kind that won
assert ha_data.infer_type(boiler) == "climate", ha_data.type_scores(boiler)
assert ha_data.effective_type(boiler) == "climate"
assert ha_data.effective_kind(boiler) == "boiler", ha_data.effective_kind(boiler)
card = ha_data.compact_device(boiler)
assert card["type"] == "climate" and card["icon"] == "water-boiler", card
assert ha_data.infer_type(washer) == "appliance", ha_data.type_scores(washer)
assert ha_data.infer_type(plug) == "iot", ha_data.type_scores(plug)                # a kind of the iot group itself stays iot

# Home Assistant: the old group
facts = ha_data.device_facts(boiler)
assert facts["type"] == "iot" and facts["kind"] == "boiler", facts
data = ha_notify.event_data({"kind": "new", "card": "b1", "params": {"label": "Caldaia", "ip": "192.0.2.40", **facts}})
assert data["type"] == "iot" and data["kind"] == "boiler", data
desired = mqtt_payloads.build_desired({"b1": boiler}, {"b1": "climate"}, 0, set(), None, {"b1": "boiler"})
attrs = [json.loads(v) for k, v in desired.items() if k.endswith("/attrs")]
assert attrs and attrs[0]["type"] == "iot" and attrs[0]["kind"] == "boiler", desired
configs = [json.loads(v) for k, v in desired.items() if k.endswith("vedetta_b1/config")]
assert configs and all(c["dev"]["model"] == "iot" for c in configs), configs
assert device_groups.ha_group("climate") == "iot" and device_groups.ha_group("router") == "router" and device_groups.ha_group(None) is None

# a type chosen by hand: a new group is kept, an old "iot" stays iot
assert ha_data.effective_type(boiler, {"type_user": "security"}) == "security"
assert ha_data.effective_type(boiler, {"type_user": "iot"}) == "iot"
assert ha_data.device_facts(boiler, {"type_user": "security"})["type"] == "iot"

# the evidence and the analysis judge a smart home group by the points of "iot", where it was scored: no rival, no override
rows = [{"group": "iot", "family": "word", "pts": 8, "source": "word caldaia", "counted": True}]
debug_type = {"chosen": "climate", "scores": {"iot": 8}, "evidence": rows, "min_score": 2}
g = evidence.group_evidence(debug_type, boiler)
as_iot = evidence.group_evidence({**debug_type, "chosen": "iot"}, boiler)
assert g["value"] == "climate" and g["rejected"] == [] and g["certainty"] == as_iot["certainty"] and g["clues"] == as_iot["clues"], (g, as_iot)
judged = status.assess(g, age_s=10 ** 6, scores={"iot": 8}, chosen="climate")
assert judged == status.assess(as_iot, age_s=10 ** 6, scores={"iot": 8}, chosen="iot") and "override" not in judged.reasons, judged

# 16 groups, the new ones right after iot
assert len(ha_data.TYPE_ORDER) == 16 and ha_data.TYPE_ORDER == device_groups.TYPE_ORDER, ha_data.TYPE_ORDER
assert ha_data.TYPE_ORDER[6:13] == ("iot", "climate", "appliance", "energy", "security", "cover", "water"), ha_data.TYPE_ORDER
print("ok: the smart home groups are on the page, Home Assistant still sees iot")

# the export for the developer keeps the new groups (an unknown one would become "other")
from app.export import export_analysis  # noqa: E402
assert set(device_groups.TYPE_ORDER) <= export_analysis.ALLOWED_GROUPS, set(device_groups.TYPE_ORDER) - export_analysis.ALLOWED_GROUPS
print("ok: the export keeps the new groups")

# the masked name of a device known only by its group: a smart home group is still told as "IoT", as before
from app.export import anonymize  # noqa: E402
masker = anonymize.Anonymizer()
assert masker.add_device(["boh-4567"], "climate") == "IoT-1" and masker.add_device(["boh-4568"], "iot") == "IoT-2"
print("ok: the masked names keep IoT")

# what is stored per MAC (history mac_memory.grp) keeps the group of before, and a smart home group is never "another device" next to an
# "iot" saved by 1.0.3 (recognition/same_device): nothing stored has to be migrated
from app.export import mac_shadow  # noqa: E402
from app.recognition import same_device  # noqa: E402
assert mac_shadow._group(boiler) == "iot", mac_shadow._group(boiler)
assert not same_device._group_differs({"grp": "iot"}, {"grp": "climate"}) and same_device._group_differs({"grp": "iot"}, {"grp": "router"})
print("ok: the memory per MAC keeps iot")
