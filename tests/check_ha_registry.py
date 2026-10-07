"""Home Assistant registry: MAC index, exclusion of devices created by Vedetta and of disabled ones."""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import ha_registry  # noqa: E402

entries = [{"entry_id": "e_shelly", "domain": "shelly", "title": "Cancello"}, {"entry_id": "e_mqtt", "domain": "mqtt", "title": "MQTT"},
           {"entry_id": "e_fritz", "domain": "fritz", "title": "FRITZ!Box"}]
areas = [{"area_id": "soggiorno", "name": "Soggiorno"}]
devices = [
    # real device, with a user-chosen name
    {"id": "d1", "name": "shelly1-8CAAB50000A2", "name_by_user": "Cancello", "manufacturer": "Shelly", "model": "Shelly 1",
     "area_id": "soggiorno", "config_entries": ["e_shelly"], "connections": [["mac", "8C:AA:B5:00:00:A2"]], "identifiers": [["shelly", "x"]]},
    # created by Vedetta via MQTT: to be excluded (vicious circle)
    {"id": "d2", "name": "Cancello", "config_entries": ["e_mqtt"], "connections": [["mac", "8c:aa:b5:00:00:a2"]], "identifiers": [["mqtt", "vedetta_scan_192_168_178_99"]]},
    # real device that Vedetta's MQTT attached to by MAC (it also has Vedetta's identifier): it stays
    {"id": "d3", "name": "Termostato", "manufacturer": "Tasmota", "model": "Sonoff TH", "config_entries": ["e_shelly", "e_mqtt"],
     "connections": [["mac", "5C:CF:7F:00:00:A7"]], "identifiers": [["tasmota", "t1"], ["mqtt", "vedetta_scan_x"]]},
    # disabled (old FRITZ!Box tracking): excluded
    {"id": "d4", "name": "PC-192-168-50-104", "disabled_by": "config_entry", "config_entries": ["e_fritz"], "connections": [["mac", "BC:24:11:00:00:B3"]], "identifiers": []},
    # without a MAC: it does not attach
    {"id": "d5", "name": "Pixel 7", "manufacturer": "Google", "model": "Pixel 7", "connections": [], "identifiers": [["mobile_app", "p"]]},
]
entities = [{"device_id": "d1", "name": "Cancelletto"}, {"device_id": "d1", "original_name": "Switch", "disabled_by": "user"}]
# without a MAC but with a configuration address (AdGuard Home, Proxmox): it attaches by IP
devices.append({"id": "d6", "name": "AdGuard Home", "manufacturer": "AdGuard Team", "config_entries": ["e_shelly"], "connections": [],
                "identifiers": [["adguard", "x"]], "configuration_url": "http://192.168.50.2:3000/"})
devices.append({"id": "d7", "name": "Web", "configuration_url": "https://example.com/", "config_entries": [], "connections": [], "identifiers": []})
# a host with several devices on the same address (Proxmox with its VMs): ambiguous, discarded
for n in (1, 2):
    devices.append({"id": f"vm{n}", "name": f"QEMU vm{n}", "config_entries": [], "connections": [], "identifiers": [["proxmoxve", f"{n}"]],
                    "configuration_url": "https://192.168.50.201:8006/"})
full = ha_registry.build_index(devices, entities, areas, entries)
idx, by_ip = full["by_mac"], full["by_ip"]
assert set(idx) == {"8c:aa:b5:00:00:a2", "5c:cf:7f:00:00:a7"}, set(idx)
assert set(by_ip) == {"192.168.50.2"} and by_ip["192.168.50.2"]["manufacturer"] == "AdGuard Team"
c = idx["8c:aa:b5:00:00:a2"]
assert c["name"] == "Cancello" and c["name_by_user"] and c["manufacturer"] == "Shelly" and c["model"] == "Shelly 1"
assert c["area"] == "Soggiorno" and c["domains"] == ["shelly"] and c["entity_names"] == ["Cancelletto"]
assert idx["5c:cf:7f:00:00:a7"]["manufacturer"] == "Tasmota"

# lookup normalizes the MAC; without data and without a token nothing breaks
ha_registry._state["by_mac"] = idx
ha_registry._state["by_ip"] = by_ip
# the function is a step of the search flows: if turned off there, the registry is not used
from app.storage import settings  # noqa: E402
settings.CONFIG_DIR = Path(tempfile.mkdtemp()); settings.SETTINGS_PATH = settings.CONFIG_DIR / "settings.json"
assert "ha_registry" in settings.flows_load()["associative"] and "ha_registry" in settings.flows_load()["deep"]
assert ha_registry.active()
settings.flows_update({"associative": ["arp_dummy"] if False else ["onvif"], "deep": ["onvif"]})
assert not ha_registry.active() and ha_registry.lookup("8C:AA:B5:00:00:A2") is None
settings.flows_reset()
assert ha_registry.active()
assert ha_registry.lookup("BC:24:11:00:00:A4", "192.168.50.2")["name"] == "AdGuard Home"   # unknown MAC: by IP
assert ha_registry.lookup("8C-AA-B5-00-00-A2")["name"] == "Cancello" and ha_registry.lookup(None) is None and ha_registry.lookup("xx") is None
os.environ.pop("SUPERVISOR_TOKEN", None)
assert ha_registry.status()["enabled"] is False
assert asyncio.run(ha_registry.refresh()) is False and "SUPERVISOR_TOKEN" in ha_registry.status()["error"]
print("TUTTO OK")
