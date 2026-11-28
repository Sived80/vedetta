# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""1.1.1: inside the printer group the page shows two families, like the families of the smart home group: printers (paper printers and
scanners) and 3D printers. Home Assistant keeps seeing "printer" (MQTT attribute and model "type", events "type"): only the page has the
second level. A family can be chosen by hand (family_user) among the families of the card's own group: a smart home family saved on a
card that is now a printer (or a printer family on a smart home card) is not used. Invented values only."""
import json
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import device_groups
from app.ha import ha_data, mqtt_payloads

failed = 0


def check(cond, msg):
    global failed
    print(("ok: " if cond else "FAILED: ") + msg)
    failed += 0 if cond else 1


printer3d = {"id": "p3", "ip": "192.0.2.60", "name": "Stampante 3D garage", "mac": "02:00:00:00:00:60", "online": True, "extra": {}}
paper = {"id": "pp", "ip": "192.0.2.61", "name": "Office printer", "mac": "02:00:00:00:00:61", "online": True, "extra": {},
         "scanned_ports": [{"label": "631 · ipp", "confirmed": True}]}
boiler = {"id": "b1", "ip": "192.0.2.40", "name": "Caldaia", "mac": "02:00:00:00:00:40", "online": True, "extra": {}}

# the families of the printer group, from the kinds of data/device_kinds.json
check(getattr(device_groups, "PRINTER_FAMILIES", None) == ("printers", "printer3d"), "the printer group has two families: printers, 3D printers")
check(device_groups.family_of("printer3d", "printer") == "printer3d", "the kind printer3d is in the family of 3D printers")
check(device_groups.family_of("printer", "printer") == "printers" and device_groups.family_of("scanner", "printer") == "printers",
      "paper printers and scanners are in the family of printers")
check(device_groups.family_of("light", "iot") == "lights" and device_groups.family_of("hub", "iot") == "other", "the smart home families are unchanged")

# a family chosen by hand counts only inside the group it belongs to
chosen = device_groups.chosen_family
try:
    check(chosen("printer3d", "printers", "printer") == "printer3d", "a printer card can be moved to the 3D printers by hand")
    check(chosen("lights", "printers", "printer") is None, "a smart home family saved on a printer card is not used")
    check(chosen("printer3d", "other", "iot") is None, "a printer family saved on a smart home card is not used")
    check(chosen("sensors", "printers", "printer") is None, "a family saved before 1.0.4 means nothing on a printer card")
except TypeError as e:
    check(False, "chosen_family knows the group of the card: %s" % e)
check(chosen("lights", "other") == "lights" and chosen("sensors", "other") == "climate", "the smart home choices read as before")

# the page: the card of a 3D printer is a printer, family 3D printers
check(ha_data.infer_type(printer3d) == "printer", "a 3D printer is in the printer group: %s" % ha_data.type_scores(printer3d))
card = ha_data.compact_device(printer3d)
check(card["type"] == "printer" and card["family"] == "printer3d" and card["family_user"] is None, "its card: family 3D printers: %s" % card["family"])
card = ha_data.compact_device(paper)
check(card["type"] == "printer" and card["family"] == "printers", "a paper printer: family printers: %s" % card["family"])
card = ha_data.compact_device(printer3d, {"family_user": "printers"})
check(card["family"] == "printers" and card["family_user"] == "printers", "moved by hand to the printers, and shown as a choice: %s" % card)
card = ha_data.compact_device(paper, {"family_user": "printer3d"})
check(card["family"] == "printer3d" and card["family_user"] == "printer3d", "a paper printer moved to the 3D printers by hand")
card = ha_data.compact_device(printer3d, {"family_user": "lights"})
check(card["family"] == "printer3d" and card["family_user"] is None, "a smart home family does not leak into the printer group: %s" % card)
card = ha_data.compact_device(boiler, {"family_user": "printer3d"})
check(card["family"] == "climate" and card["family_user"] is None, "a printer family does not leak into the smart home group: %s" % card)
card = ha_data.compact_device(boiler, {"type_user": "printer"})
check(card["type"] == "printer" and card["family"] == "printers", "a card set to printer by hand, with no printer kind: family printers")
check(ha_data.compact_device(printer3d, {"type_user": "camera"})["family"] is None, "outside the two groups no family")

# Home Assistant: the same group as before, the kind tells the 3D printer
facts = ha_data.device_facts(printer3d)
check(facts["type"] == "printer" and facts["kind"] == "printer3d", "the events say printer, kind printer3d: %s" % facts)
desired = mqtt_payloads.build_desired({"p3": printer3d}, {"p3": "printer"}, 0, set(), None, {"p3": "printer3d"})
attrs = [json.loads(v) for k, v in desired.items() if k.endswith("/attrs")]
check(bool(attrs) and attrs[0]["type"] == "printer" and "family" not in attrs[0], "MQTT says printer and knows no family")

# the choice is accepted by the two routes that save it
from app.routes import device_routes, passive_routes  # noqa: E402
src = open(device_routes.__file__, encoding="utf-8").read() + open(passive_routes.__file__, encoding="utf-8").read()
check(src.count("device_groups.ALL_FAMILIES") == 2, "both routes accept the families of every group")
check(set(getattr(device_groups, "ALL_FAMILIES", ())) == set(device_groups.FAMILIES) | {"printers", "printer3d"}, "every family is known")

print("FAILED: %d" % failed if failed else "ALL OK")
sys.exit(1 if failed else 0)
