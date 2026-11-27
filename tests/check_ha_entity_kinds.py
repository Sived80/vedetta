"""1.0.4: the type of a device as Home Assistant knows it. HA does not guess from names: each integration declares the entity DOMAINS
(cover, switch, climate...) and the DEVICE CLASSES (cover gate/garage/shutter, switch outlet, sensor temperature...). The registry keeps per
device the sorted "domain" / "domain.device_class" signatures of its primary entities (device_class chosen by the user first, then the
original one; config and diagnostic entities left out), and data/ha_entity_kinds.json turns them into a kind of data/device_kinds.json:
an actuator beats its sensors, diagnostic sensors never decide. A kind declared this way is stronger than a word of the name; a manual
choice still wins; Home Assistant keeps seeing "iot" (MQTT attribute and events "type"). Invented names and addresses only."""
import json
import os
import sys
import tempfile

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import datafile  # noqa: E402
from app.ha import ha_data, ha_registry  # noqa: E402

failed = 0


def check(cond: bool, msg: str) -> None:
    global failed
    print(("ok: " if cond else "FAILED: ") + msg)
    failed += 0 if cond else 1


# ---- 1) the registry reads the device classes: device_class (the user's) first, then original_device_class
DEVICES = [{"id": "d1", "name": "Node", "connections": [["mac", "02:00:00:00:00:61"]], "config_entries": ["e1"]}]
ENTITIES = [
    {"entity_id": "cover.node", "device_id": "d1", "device_class": "gate", "original_device_class": "garage"},   # the user's choice wins
    {"entity_id": "sensor.node_t", "device_id": "d1", "device_class": None, "original_device_class": "temperature"},
    {"entity_id": "switch.node", "device_id": "d1"},                                                               # no class: the domain alone
    {"entity_id": "sensor.node_rssi", "device_id": "d1", "original_device_class": "signal_strength", "entity_category": "diagnostic"},
    {"entity_id": "switch.node_led", "device_id": "d1", "entity_category": "config"},
    {"entity_id": "sensor.node_x", "device_id": "d1", "original_device_class": "Not A Class!"},                    # not a standard word: domain only
    {"entity_id": "light.node_off", "device_id": "d1", "disabled_by": "user"},
]
index = ha_registry.build_index(DEVICES, ENTITIES, [], [{"entry_id": "e1", "domain": "acme_hub", "title": "Node"}])
card = index["by_mac"]["02:00:00:00:00:61"]
check(card.get("entity_classes") == ["cover.gate", "sensor", "sensor.temperature", "switch"],
      "signatures from device_class, then original_device_class; config, diagnostic and disabled entities left out: %s" % card.get("entity_classes"))
check(card["entity_domains"] == ["cover", "sensor", "switch"], "entity_domains unchanged: %s" % card["entity_domains"])


# ---- 2) the kind from the signatures
def device(name: str, classes: list, domains=("acme_hub",)) -> dict:
    ent_domains = sorted({c.split(".")[0] for c in classes})
    reg = {"name": name, "name_by_user": True, "manufacturer": None, "model": None, "area": None, "domains": list(domains), "entry_titles": [],
           "observer_titles": [], "sw_version": None, "entity_names": [], "entity_domains": ent_domains, "entity_classes": sorted(classes)}
    return {"id": "k1", "ip": "192.0.2.61", "name": name, "mac": "02:00:00:00:00:61", "online": True, "extra": {}, "ha_registry": reg}


def seen(dev: dict, cfg: dict | None = None) -> tuple:
    return (ha_data.effective_type(dev, cfg), ha_data.effective_kind(dev, cfg), ha_data.compact_device(dev, cfg)["family"],
            ha_data.device_facts(dev, cfg)["type"])


CASES = (
    ("Presa garage", ["cover.gate"], "gate", "security"),                                      # HA says gate: the plug word does not decide
    ("Garage", ["switch.outlet", "sensor.power", "sensor.energy"], "plug", "lights"),           # a plug that measures power is a plug
    ("Sala", ["cover.shutter", "sensor.temperature"], "blinds", "climate"),                     # the actuator beats its sensor
    ("Sala", ["climate", "sensor.temperature", "sensor.humidity"], "thermostat", "climate"),
    ("Corridoio", ["light", "sensor.power"], "light", "lights"),
    ("Cucina", ["binary_sensor.moisture", "sensor.battery"], "leak", "security"),
    ("Studio", ["sensor.temperature", "sensor.humidity", "sensor.battery"], "temperature", "climate"),
    ("Quadro", ["sensor.power", "sensor.energy", "sensor.voltage"], "meter", "energy"),         # power alone: a meter
    ("Condizionatore", ["climate"], "aircon", "climate"),                                       # a finer word of the same function
)
for name, classes, kind, family in CASES:
    got = seen(device(name, classes))
    check(got == ("iot", kind, family, "iot"), "%s %s: kind %s, family %s, Home Assistant sees iot: %s" % (name, classes, kind, family, got))

# only diagnostic sensors (and buttons, numbers, updates): no kind from the entities
diag = device("Nodo", ["sensor.signal_strength", "sensor.battery", "button", "number", "update"])
check(ha_data.effective_kind(diag) is None, "only diagnostic entities name no kind: %s" % ha_data.effective_kind(diag))
# a plain switch is weak: a word of the name still names the device
check(seen(device("Lavatrice", ["switch", "sensor.power"]))[1] == "washer", "a plain switch does not beat a word: %s" % (seen(device("Lavatrice", ["switch", "sensor.power"])),))
# a manual choice still wins over everything
gate = device("Presa garage", ["cover.gate"])
check(ha_data.compact_device(gate, {"family_user": "energy"})["family"] == "energy", "the family chosen by hand wins")
check(ha_data.effective_type(gate, {"type_user": "media"}) == "media", "the group chosen by hand wins")
# a client that only a router integration observes: its entities are the router's, not a function
observed = device("Telefono", ["switch", "sensor.data_rate", "device_tracker"], domains=("unifi",))
check(ha_data.effective_kind(observed, None) != "switch", "an observed client gets no kind from the router's entities: %s" % ha_data.effective_kind(observed))
# a card saved before the classes were read says nothing more than before
old = device("Presa garage", ["cover.gate"])
del old["ha_registry"]["entity_classes"]
check(seen(old)[1] == "plug", "a card without entity_classes keeps the old result: %s" % (seen(old),))

# ---- 3) the table: every kind it names is a kind of data/device_kinds.json
table = json.loads((datafile.DATA_DIR / "ha_entity_kinds.json").read_text(encoding="utf-8"))
known = {k["id"] for k in json.loads((datafile.DATA_DIR / "device_kinds.json").read_text(encoding="utf-8"))["kinds"]}
named = {row["kind"] for tier in table["tiers"] for row in tier["kinds"].values()} | {f for tier in table["tiers"] for row in tier["kinds"].values() for f in row.get("finer", [])}
check(named <= known, "the table names only known kinds: %s" % sorted(named - known))

# ---- 4) the export keeps the signatures readable: standard words, never a name ("sensor.ph" is no domain name)
from app.export import anonymize  # noqa: E402
sigs = ["binary_sensor.door", "cover.gate", "sensor.ph", "switch"]
check(anonymize.Anonymizer().data({"ha_registry": {"entity_classes": sigs}})["ha_registry"]["entity_classes"] == sigs, "the export keeps entity_classes as they are")

print("FAILED: %d" % failed if failed else "ALL OK")
sys.exit(1 if failed else 0)
