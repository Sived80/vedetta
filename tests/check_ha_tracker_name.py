"""A client that a network integration only tracks (a device_tracker made by a router integration) must not be named after that integration.
Real shape (a shared export, masked): 11 of 51 cards were called by the title of the router integration, among them a vacuum, a laptop and an access point;
the registry knew each of them only as a tracker, with the MAC as the device name."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import ha_registry  # noqa: E402


def card(name="70:C9:32:23:BB:67", titles=("Router Integration",), entities=("device_tracker",), by_user=False):
    return {"name": name, "name_by_user": by_user, "manufacturer": "", "model": None, "area": None, "domains": ["router_integration"],
            "entry_titles": list(titles), "entity_domains": None if entities is None else list(entities)}


# a tracked client: the MAC is no name and the title of the tracking integration is not the name of the client
assert ha_registry.choose_name(card()) == (None, None), ha_registry.choose_name(card())
# the same client with a real device name keeps it
assert ha_registry.choose_name(card(name="Garden vacuum")) == ("Garden vacuum", "ha")
# a name chosen by the user always wins
assert ha_registry.choose_name(card(name="Garage AP", by_user=True)) == ("Garage AP", "ha_user")
# a device that its integration really declares (sensors, switches...) may still be named by the title of the integration
assert ha_registry.choose_name(card(entities=("device_tracker", "sensor"))) == ("Router Integration", "ha")
# an export or registry that does not say which entities exist: nothing is assumed, as before
assert ha_registry.choose_name(card(entities=None)) == ("Router Integration", "ha")
print("TUTTO OK")
