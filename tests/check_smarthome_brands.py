"""Issue #36 (export of 13/11): Tuya, Netatmo and Rademacher devices stayed in "other devices": the brand was known (from the MAC) but no clue
gave a group. Tuya and Rademacher make (almost) only smart-home devices, so their brand is a clue for the group "iot" (data/device_kinds.json,
kind "smarthome"), and so is the Rademacher HomePilot gateway's mDNS service; Netatmo also makes cameras, so it is only a word of the group
(data/type_words.json). A stronger clue still wins.
    python tests/check_smarthome_brands.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import ha_data  # noqa: E402

# what the FRITZ!Box integration of HA says about a client, as in the export: it only observes it (no clue for the group)
FRITZ = {"name": None, "manufacturer": "FRITZ!", "model": None, "domains": ["fritz"], "entry_titles": ["FRITZ!Box 7590"],
         "observer_titles": ["FRITZ!Box 7590"], "entity_names": ["Internetzugang"], "entity_domains": ["device_tracker", "switch"]}


def card(brand, vendor, ports=(), services=None, name=None):
    return {"ip": "10.0.0.15", "name": name, "brand": brand, "vendor": vendor, "vendor_role": "brand", "is_mobile": False,
            "scanned_ports": [{"port": p, "label": lbl} for p, lbl in ports], "extra": {"mdns_services": services} if services else {},
            "ha_registry": dict(FRITZ)}


# 1. the cards of the export: brand from the MAC, nothing else
assert ha_data.infer_type(card("Tuya", "Tuya", [(6668, "irc")], name="Tuya-2")) == "iot"
assert ha_data.infer_type(card("Netatmo", "Netatmo", [(5001, "commplex-link")], "_hap._tcp")) == "iot"
assert ha_data.infer_type(card("Rademacher Geraete-Elektronik", "Rademacher Geraete-Elektronik", [(80, "nginx"), (443, "nginx")],
                               "_homepilot._tcp, _matter._tcp")) == "iot"
# 2. the HomePilot service alone (no brand) says smart home too
assert ha_data.infer_type(card(None, None, [(80, "nginx")], "_homepilot._tcp")) == "iot"
# 3. Netatmo also makes cameras, so it is a word of the smart home (2 points), not a brand of it (3): a camera that says so still wins
cam = card("Netatmo", "Netatmo", [(554, "rtsp")])
cam["extra"] = {"onvif_hardware": "Welcome", "onvif_manufacturer": "Netatmo"}
assert ha_data.infer_type(cam) == "camera", ha_data.type_scores(cam)

print("check_smarthome_brands OK")
