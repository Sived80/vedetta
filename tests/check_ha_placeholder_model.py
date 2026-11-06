"""Issue #36: an integration that only OBSERVES the network (a router integration such as FRITZ!Box Tools) makes one Home Assistant device per client with the same
placeholder model ("FRITZ!Box Tracked device") and its own manufacturer. That model must not count as the client's own product: the client is then only observed, the
observer's titles are not offered as names and the manufacturer of the observer is not the client's brand (the MAC vendor stays). The equipment itself (a model with a
firmware version) and a client that another integration owns (a camera with its own integration) keep what Home Assistant says. No code per make: the rule is "a model
shared by several devices that only observer integrations know, with no firmware version".
    python tests/check_ha_placeholder_model.py"""
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
try:
    import app.applog  # noqa: F401
except Exception:
    import logging
    stub = types.ModuleType("app.applog")
    stub.logger = logging.getLogger("dashboard")
    sys.modules["app.applog"] = stub

from app.ha import ha_registry  # noqa: E402
from app.scan import probe  # noqa: E402

ha_registry.observer_domains = lambda: frozenset({"fritz"})
ENTRIES = [{"entry_id": "e_fritz", "domain": "fritz", "title": "FRITZ!Box 7590"}, {"entry_id": "e_tapo", "domain": "tapo_control", "title": "Garden camera"}]


def device(i, model, manufacturer="FRITZ!", sw=None, entries=("e_fritz",), oui=None):
    """A Home Assistant device; the clients get MACs of different makers (oui), as on a real network."""
    prefix = oui or "AA:BB:%02X" % i
    return {"id": "d%d" % i, "name": "client-%d" % i, "manufacturer": manufacturer, "model": model, "sw_version": sw, "config_entries": list(entries),
            "connections": [["mac", "%s:00:00:%02X" % (prefix, i)]]}


PLACEHOLDER = "FRITZ!Box Tracked device"
DEVICES = [device(i, PLACEHOLDER) for i in range(1, 5)] + [device(5, PLACEHOLDER, sw="1.3.1 Build 20240630")]   # the router also reports the firmware of some clients
DEVICES.append(device(20, "FRITZ!Box 7590", sw="8.02"))                                          # the router itself: a model with a firmware
DEVICES.append(device(21, "C200", manufacturer="TP-Link", entries=("e_fritz", "e_tapo")))        # a camera with its own integration (owned by it)
DEVICES.append(device(22, "FRITZ!Repeater 3000", sw="7.5"))                                      # one repeater: a real product
ENTITIES = [{"device_id": "d%d" % i, "entity_id": "device_tracker.c%d" % i} for i in range(1, 6)] + \
           [{"device_id": "d%d" % i, "entity_id": "switch.c%d_internet_access" % i} for i in range(1, 6)] + \
           [{"device_id": "d20", "entity_id": "sensor.router_uptime"}, {"device_id": "d21", "entity_id": "camera.garden"}, {"device_id": "d21", "entity_id": "device_tracker.garden"}]

idx = ha_registry.build_index(DEVICES, ENTITIES, [], ENTRIES)["by_mac"]


def card(i):
    return next(c for m, c in idx.items() if m.endswith(":00:00:%02x" % i))


client, client_fw, router, camera, repeater = card(1), card(5), card(20), card(21), card(22)
OBS = ha_registry.observer_domains()

# 1) the placeholder model is not the client's product: the client is only observed, the router's title is not a name for it
assert client["model"] is None, client
assert ha_registry.observed_only(client, OBS), client
assert client["observer_titles"] == ["FRITZ!Box 7590"], client
assert client_fw["model"] is None and ha_registry.observed_only(client_fw, OBS), "a client with a firmware reported by the router is still a client: %r" % client_fw
# 2) the equipment itself and the owned camera keep their model
assert router["model"] == "FRITZ!Box 7590" and not ha_registry.observed_only(router, OBS), router
assert repeater["model"] == "FRITZ!Repeater 3000", repeater
assert camera["model"] == "C200", camera                      # owned by its own integration (observed_only is True there: the observer does not own it)

# 3) the brand: the observer's manufacturer does not replace the MAC vendor of a client; it does for the owned camera and the router
MAC_BRAND = {"brand": "Netatmo", "brand_source": "mac", "brand_confidence": "medium"}
assert probe._chosen_brand(dict(MAC_BRAND), client, {})["brand"] == "Netatmo", "the observer's manufacturer replaced the MAC vendor"
assert probe._chosen_brand(dict(MAC_BRAND), client_fw, {})["brand"] == "Netatmo", client_fw
assert probe._chosen_brand(dict(MAC_BRAND), camera, {})["brand_source"] == "ha"
assert probe._chosen_brand(dict(MAC_BRAND), router, {})["brand_source"] == "ha"

# 4) three identical access points of the observer itself (same maker, same model, a firmware) are real equipment, not a placeholder
APS = [device(30 + k, "U6-Lite", manufacturer="Ubiquiti", sw="6.6.77", oui="24:5A:4C") for k in range(3)]
idx2 = ha_registry.build_index(APS, [], [], ENTRIES)["by_mac"]
assert all(c["model"] == "U6-Lite" for c in idx2.values()), idx2
# 5) a single client of an observer is left as it was (no evidence of a shared placeholder)
ONE = [device(40, "Some model")]
assert next(iter(ha_registry.build_index(ONE, [], [], ENTRIES)["by_mac"].values()))["model"] == "Some model"
print("TUTTO OK")
