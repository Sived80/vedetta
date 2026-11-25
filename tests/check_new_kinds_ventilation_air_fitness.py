"""Three device types asked by users (data/device_kinds.json, words of the function, no brand): mechanical ventilation with heat recovery, air quality / CO2 sensors and gym
equipment. Their icons exist in icons.js (a missing one would silently fall back to the category icon)."""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import ha_data  # noqa: E402

APP = Path(__file__).resolve().parent.parent / "vedetta" / "app"


def kind_of(name: str):
    return ha_data.best_kind({"ip": "192.0.2.31", "mac": "02:00:00:00:00:31", "name": name, "scanned_ports": []})


for name, want in (("VMC soggiorno", "ventilation"), ("Recuperatore di calore", "ventilation"), ("MVHR loft", "ventilation"), ("Heat recovery unit", "ventilation"),
                   ("Ventilazione meccanica", "ventilation"),
                   ("Sensore CO2 ufficio", "airquality"), ("Sensore qualità aria", "airquality"), ("Air quality monitor", "airquality"), ("IAQ sensor", "airquality"),
                   ("Treadmill", "fitness"), ("Tapis roulant", "fitness"), ("Home gym", "fitness"), ("Fitness bike", "fitness"), ("Attrezzo palestra", "fitness")):
    got = kind_of(name)
    assert got == want, "%r: %s, wanted %s" % (name, got, want)

# the short words count only as whole words
for name in ("vmware host", "fitnessroom", "gymnastics clock", "carbon monoxide detector"):
    got = kind_of(name)
    assert got not in ("ventilation", "airquality", "fitness"), "%r must not be a new type: %s" % (name, got)

icons = set(re.findall(r'^\s*"([a-z0-9-]+)":\s*"M', (APP / "static" / "ha" / "icons.js").read_text(encoding="utf-8"), re.M))
kinds = json.loads((APP / "data" / "device_kinds.json").read_text(encoding="utf-8"))["kinds"]
missing = sorted({k["icon"] for k in kinds if k["id"] in ("ventilation", "airquality", "fitness")} - icons)
assert not missing, "icons of device types not in icons.js: %s" % missing
print("ALL OK")
