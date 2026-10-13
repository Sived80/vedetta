"""An integration of Home Assistant that OBSERVES the network (UniFi, MikroTik, FRITZ!...) creates entities for the clients it sees (tracker, bandwidth sensors, block switches): that says the device is on the network,
not that it is a router. It declares a device only when the registry holds a product of its own - a model or a firmware version - and no other integration owns the device. Seen in the exports of two makers: the 7 UniFi
devices that are network equipment have a model and a firmware (UAL6, USMINI, 6.7.57...), the 12 clients do not (model None; Proxmox, Raspberry Pi, a printer, a TV box... all read as routers with 8 points before); the
MikroTik router has model hEX, its clients none. The test is made from the data: EVERY integration flagged "observer" in data/ha_integrations.json."""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import ha_data  # noqa: E402
from app.ha import ha_type_evidence as T  # noqa: E402

TABLE = json.loads((Path(__file__).parent.parent / "vedetta" / "app" / "data" / "ha_integrations.json").read_text(encoding="utf-8"))["integrations"]
OBSERVERS = sorted(k for k, v in TABLE.items() if v.get("observer"))
assert {"unifi", "mikrotik", "fritz", "fritzbox", "tplink_router"} <= set(OBSERVERS), OBSERVERS
assert all(TABLE[k]["group"] == "router" for k in OBSERVERS), "an observer integration is one of the network equipment"


def card(domains, model=None, sw=None, entities=("sensor",), ports=("22 ssh",), name="Proxmox-1"):
    reg = {"name": "x", "domains": domains, "model": model, "sw_version": sw, "entity_domains": list(entities), "entry_titles": ["Hub"], "manufacturer": None}
    return {"id": "x", "ip": "10.0.0.50", "name": name, "name_generated": False, "brand": None, "vendor": None, "vendor_role": None, "extra": {},
            "scanned_ports": [{"label": p, "confirmed": True} for p in ports], "ha_registry": reg, "is_mobile": False}


def integration_clues(device):
    return [c for c in T._Clues(device, None, {}).collect() if c["source"].startswith("integrazione HA")]


# 1. the class, from the data: for every observer integration a client (no model, no firmware) gives no clue, the equipment itself (model and firmware) gives its group
for dom in OBSERVERS:
    assert not integration_clues(card([dom])), "%s: a client observed by it must not be declared a router" % dom
    assert [c["group"] for c in integration_clues(card([dom], model="M1", sw="1.0"))] == ["router"], "%s: the equipment itself is declared" % dom
    assert [c["group"] for c in integration_clues(card([dom], sw="1.0"))] == ["router"], "%s: a firmware alone is a product too" % dom

# 2. a device owned by another integration is not declared by the observer, even if the registry holds a model (the model is the owner's)
assert not [c for c in integration_clues(card(["unifi", "shelly"], model="Shelly UNI", sw="1.13")) if "unifi" in c["source"]]

# 3. what the observed client IS comes from its other clues (a server with its SSH port), not from the observer
assert ha_data.infer_type(card(["unifi"]), None) == "server", ha_data.infer_type(card(["unifi"]), None)
assert ha_data.infer_type(card(["unifi"], model="UAL6", sw="6.7.57", entities=("button", "light", "sensor", "update"), ports=()), None) == "router"
assert ha_data.infer_type(card(["unifi"], ports=(), name="Device-1"), None) == "generic", "a client with no other clue is not known: it goes to the state of analysis, not to router"

# 3b. a registry saved before it told the product (no model, no firmware key at all) says nothing: the integration declares as it always did
legacy = card(["unifi"])
del legacy["ha_registry"]["model"], legacy["ha_registry"]["sw_version"]
assert [c["group"] for c in integration_clues(legacy)] == ["router"]

# 4. the integrations that are not observers are not touched
assert [c["group"] for c in integration_clues(card(["sonos"]))] == ["audio"]
print("TUTTO OK")
