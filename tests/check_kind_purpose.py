# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""1.0.4 (27/11): three choices of the person on the groups.
1) A word of the NAME that says what the device is FOR (alarm, siren; gateway: bridge, coordinator, proxy, beacon, IRK) beats what it is made
   of, even what Home Assistant declares: an "LED allarme esterno" is a light entity in HA but belongs to the alarm. Only the name (and the
   model HA declares) counts, never the web title or other texts of the device; a manual choice still wins.
2) Gates, garage doors and doors are a family of their own, "access" ("Cancelli e porte"), out of security.
3) The gateways of the smart home (Zigbee, Z-Wave, Thread, Bluetooth bridges and proxies) are network: group "router" ("Rete").
   The word "zigbee" alone is a protocol, not a gateway: a Zigbee door sensor stays in the smart home.
Invented names and addresses only.
    python tools/run_test.py check_kind_purpose.py"""
import os
import sys
import tempfile

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import ha_data  # noqa: E402
from app import device_groups  # noqa: E402

failed = 0


def check(cond: bool, msg: str) -> None:
    global failed
    print(("ok: " if cond else "FAILED: ") + msg)
    failed += 0 if cond else 1


def device(name: str, classes: list, extra: dict | None = None, model: str | None = None) -> dict:
    reg = {"name": name, "name_by_user": True, "manufacturer": None, "model": model, "area": None, "domains": ["esphome"], "entry_titles": [],
           "observer_titles": [], "sw_version": None, "entity_names": [], "entity_domains": sorted({c.split(".")[0] for c in classes}),
           "entity_classes": sorted(classes)}
    ext = {"mdns_services": "_esphomelib._tcp", **(extra or {})}
    if model:
        ext["ha_model"] = model
    return {"id": "p1", "ip": "192.0.2.71", "name": name, "mac": "02:00:00:00:00:71", "online": True, "extra": ext, "ha_registry": reg}


def seen(dev: dict, cfg: dict | None = None) -> tuple:
    return ha_data.effective_type(dev, cfg), ha_data.effective_kind(dev, cfg), ha_data.compact_device(dev, cfg)["family"]


# 1) the purpose in the name beats the light entity
got = seen(device("LED allarme esterno", ["light"]))
check(got[0] == "iot" and got[1] == "alarm" and got[2] == "security", "an LED of the alarm is in security, not in lights: %s" % (got,))
got = seen(device("Sirena giardino", ["light", "switch"]))
check(got[2] == "security", "a siren with a light entity is in security: %s" % (got,))
check(seen(device("LED allarme esterno", ["light"]), {"family_user": "lights"})[2] == "lights", "a manual family still wins")
check(seen(device("Luce cucina", ["light"]))[2] == "lights", "a light with no purpose word stays a light")
cam = {"id": "c1", "ip": "192.0.2.72", "name": "Telecamera ingresso", "mac": "02:00:00:00:00:72", "online": True,
       "extra": {"http_title": "Alarm Settings", "mdns_services": "_onvif._tcp"}}
check(ha_data.effective_type(cam) == "camera", "a word of the web title is no purpose: the camera stays a camera (%s)" % ha_data.effective_type(cam))

# 2) gates and garage doors: their own family
check("access" in device_groups.FAMILIES, "a family for gates and doors: %s" % (device_groups.FAMILIES,))
for name, classes in (("Cancelletto", ["switch"]), ("Cancello", ["cover.gate"]), ("Porta garage", ["cover.garage"])):
    got = seen(device(name, classes))
    check(got[0] == "iot" and got[2] == "access", "%s %s: family access: %s" % (name, classes, got))
check(seen(device("Sensore porta", ["binary_sensor.door"]))[2] == "security", "a door contact sensor stays in security")

# 3) the gateways are network
zb = device("Gateway Zigbee", [], model="ZbBridge")
zb["extra"].pop("mdns_services")
got = seen(zb)
check(got[0] == "router" and got[1] == "hub" and got[2] is None, "a Zigbee bridge is in the network group: %s" % (got,))
check(ha_data.device_facts(zb)["type"] == "router", "and Home Assistant sees it as router")
got = seen(device("BLE Beacon IRK", ["binary_sensor.presence"]))
check(got[0] == "router" and got[1] == "hub", "a Bluetooth beacon/IRK node named so is a gateway, in the network group: %s" % (got,))
got = seen(device("Nodo soggiorno", ["binary_sensor.presence"], model="Bluetooth Proxy"))
check(got[0] == "router", "a model HA declares as a Bluetooth proxy is a gateway too: %s" % (got,))
got = seen(device("Sensore porta Zigbee", ["binary_sensor.door"]))
check(got[0] == "iot" and got[2] == "security", "the word zigbee alone does not make a gateway: %s" % (got,))
check(seen(device("BLE Beacon IRK", ["binary_sensor.presence"]), {"type_user": "iot"})[0] == "iot", "a manual group still wins")

if failed:
    print("%d FAILED" % failed)
    sys.exit(1)
print("ALL OK")
