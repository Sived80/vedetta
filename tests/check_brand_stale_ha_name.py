"""Issue #36 (export of 13/11): six Shelly plugs read through the FRITZ!Box integration of Home Assistant kept, as their saved name, the old name
HA gave them (the title of the FRITZ!Box, name_source "ha"). That name is stale (HA no longer offers it: the card shows another one), but the
brand was still worked out from it first: "fritz" -> AVM, and the brand AVM put the plugs in the router group. A stale name from HA is not a clue
for the brand; a name chosen in Vedetta or still given by HA is.
    python tests/check_brand_stale_ha_name.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import probe  # noqa: E402
from app.scan.probe_names import NameState  # noqa: E402
from app.scan.probe_record import Facts  # noqa: E402

SHELLY = {"http_server": "ShellyHTTP/1.0.0", "api_source": "shelly", "api_vendor": "Shelly", "api_model": "S3PL-30110EU"}
HA_CARD = {"name": "shellyplugmg3-089272000020", "name_by_user": False, "manufacturer": "FRITZ!", "model": None, "domains": ["fritz"],
           "entry_titles": ["FRITZ!Box 7590"], "observer_titles": ["FRITZ!Box 7590"], "entity_names": ["Internetzugang", "shellyplugmg3-089272000020"],
           "entity_domains": ["device_tracker", "switch"]}


def facts(name: str, source: str) -> Facts:
    device = {"id": "scan-10-0-0-71", "ip": "10.0.0.71", "name": name, "name_source": source}
    return Facts(device=device, ip="10.0.0.71", port=80, result={"online": True}, mac="08:92:72:00:00:20", extra={}, scan_info=dict(SHELLY),
                 scanned_ports=[{"port": 80, "label": "http"}], identity_mac="08:92:72:00:00:20", dhcp_name=None, dhcp_class=None, ha_card=dict(HA_CARD), key=None)


def brand(name: str, source: str) -> dict:
    f = facts(name, source)
    placeholder, ha_stale = probe._stale_name(f, name)
    names = NameState(name, placeholder, ha_stale)
    probe.choose_automatic_name(f, names)
    probe.prefer_home_assistant_name(f, names)
    return probe._probe_device_brand(f, names).ident


# 1. the case of the export: the stale name from HA is the router's; the brand comes from the plug itself (the Shelly API)
f = facts("FRITZ!Box 7590", "ha")
assert probe._stale_name(f, "FRITZ!Box 7590")[1], "the precondition: HA no longer gives this name"
got = brand("FRITZ!Box 7590", "ha")
assert got["brand"] == "Shelly", got

# 2. a name chosen in Vedetta still counts, whatever it says (the user knows the device)
assert brand("FRITZ!Box di sala", "user")["brand"] == "AVM"

print("check_brand_stale_ha_name OK")
