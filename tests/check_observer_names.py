"""A device must not be named after an integration that only OBSERVES it. The title of the config entry of UniFi, MikroTik, FRITZ!... is the name of the router or of the controller, not of the client it sees: in a real export
a vacuum, a laptop, a Shelly relay and an access point of other makers were all called "Mikrotik Router". The old fix covered the clients known only as a device_tracker (tests/check_ha_tracker_name.py); the clients that the
observer also gives sensors and switches (bandwidth, block) kept the title. The same criterion as for the type (tests/check_observer_integrations.py): an observer declares a device - and offers its title as a name - only when the
registry holds a product of its own (a model or a firmware) and no other integration owns the device. The test is made from the data: every integration flagged "observer"."""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import ha_registry  # noqa: E402

TABLE = json.loads((Path(__file__).parent.parent / "vedetta" / "app" / "data" / "ha_integrations.json").read_text(encoding="utf-8"))["integrations"]
OBSERVERS = sorted(k for k, v in TABLE.items() if v.get("observer"))
assert len(OBSERVERS) >= 5, OBSERVERS


def name_of(domains, titles, model=None, sw=None, name="70:C9:32:23:BB:67", entities=("device_tracker", "sensor", "switch")):
    """choose_name of a device made by build_index: one entry per domain, with its title."""
    entries = [{"entry_id": "E%d" % i, "domain": d, "title": t} for i, (d, t) in enumerate(zip(domains, titles))]
    dev = {"id": "D1", "name": name, "model": model, "sw_version": sw, "connections": [["mac", "08:3a:f2:00:00:05"]], "config_entries": [e["entry_id"] for e in entries]}
    ents = [{"entity_id": "%s.x" % kind, "device_id": "D1"} for kind in entities]
    card = ha_registry.build_index([dev], ents, [], entries)["by_mac"]["08:3a:f2:00:00:05"]
    return ha_registry.choose_name(card), card


for dom in OBSERVERS:
    # a client seen by the observer, with sensors and switches too: it is not named after the observer's title
    assert name_of([dom], ["Observer Title"])[0] == (None, None), dom
    # the equipment itself (model and firmware): its title may name it
    assert name_of([dom], ["Observer Title"], model="M1", sw="1.0")[0] == ("Observer Title", "ha"), dom

# a client that another integration owns (a Shelly seen by MikroTik): named after the title of its own integration, not of the observer
(shelly, card) = name_of(["mikrotik", "shelly"], ["Mikrotik Router", "Citofono"], model="Shelly UNI", sw="1.13", name="shellyuni-C45BBEE20F90")
assert shelly == ("Citofono", "ha"), shelly
assert card["entry_titles"] == ["Mikrotik Router", "Citofono"], "the debug still shows all the entries"
# an integration that is not an observer is untouched
assert name_of(["sonos"], ["Living room"], name="RINCON_7828CA")[0] == ("Living room", "ha")
# a registry saved before it told the product keeps offering the titles, as it always did
old = {"name": None, "domains": ["unifi"], "entry_titles": ["Hub"], "entity_domains": ["sensor"]}
assert ha_registry.choose_name(old) == ("Hub", "ha")

# privacy: the new key holds only strings of entry_titles, which the export already masks as names; checked on the real path of the export (a short proper name, "Leo")
from app.export import anonymize, export_zip  # noqa: E402
_, leo = name_of(["mikrotik", "shelly"], ["Router di Leo", "Citofono"], model="Shelly UNI", sw="1.13", name="shellyuni-C45BBEE20F90")
assert leo["observer_titles"] == ["Router di Leo"] and set(leo["observer_titles"]) <= set(leo["entry_titles"]), leo
ha_registry._state["by_mac"], ha_registry._state["by_ip"] = {"08:3a:f2:00:00:05": leo}, {}
anon = anonymize.Anonymizer()
export_zip._add_registry_names(anon)
masked = json.dumps(anon.data(leo, "ha_registry"))
assert "Leo" not in masked and "observer_titles" in masked, masked
print("TUTTO OK")
