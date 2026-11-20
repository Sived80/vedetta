"""1.0 step P11 (decision 2A): the new devices behind the router in the list of new devices, the same list as the home network's.
- GET /api/new-devices (newdevices.list_new) gives the rows of routed_seen whose status is "new" next to the new MACs of the home network,
  by first sight: "mac" null when Home Assistant did not say it, "network" the id of the network, "last_seen";
- never a row seen too long ago (routedinv.LISTED_S), a known one, one at the address of a card, an ignored one (by address, MAC or name);
- the watch tells the page again only when the list changes, a row without MAC counting by its address;
- the alert of a device without MAC: the words of the home network, "MAC -".
Temporary data folder, invented private addresses.
    python tests/check_routed_new.py"""
import os
import sys
import tempfile
import time

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app import newdevicewatch, routedinv  # noqa: E402
from app.routes import settings_routes  # noqa: E402
from app.storage import blocklist, devices_config, newdevices  # noqa: E402
from app.storage.history import history  # noqa: E402

now = time.time()


def row(ip, status="new", mac=None, host=None, first=None, last=None):
    return {"network": "iot", "ip": ip, "first_seen": first or now - 50, "last_seen": last or now - 10, "mac": mac, "host": host, "status": status}


history.meta_set(newdevices.BASELINE_KEY, "1")
history.known_set("02:00:5E:50:00:01", now - 100, "192.168.50.20", None, None, "new")        # a new MAC of the home network
newdevices._present = {"02:00:5E:50:00:01"}
history.routed_write([row("192.168.60.7", first=now - 60), row("192.168.60.8", mac="02:00:5E:60:00:08", host="plug", first=now - 40),
                      row("192.168.60.9", last=now - routedinv.LISTED_S - 5), row("192.168.60.10", status="known"),
                      row("192.168.60.11"), row("192.168.60.12"), row("192.168.60.13", host="guest")])
devices_config.add_devices([{"ip": "192.168.60.11", "name": "card"}])
blocklist.add("ip", "192.168.60.12")
blocklist.add("name", "guest")

got = newdevices.list_new()
assert [d["ip"] for d in got] == ["192.168.50.20", "192.168.60.7", "192.168.60.8"], got
plain, with_mac = got[1], got[2]
assert plain["mac"] is None and plain["network"] == "iot" and plain["hostname"] is None and abs(plain["last_seen"] - (now - 10)) < 1, plain
assert with_mac["mac"] == "02:00:5E:60:00:08" and with_mac["hostname"] == "plug" and with_mac["network"] == "iot", with_mac
assert "network" not in got[0], "the home network's rows are as before"

app = FastAPI()
app.include_router(settings_routes.router)
assert [d["ip"] for d in TestClient(app).get("/api/new-devices").json()] == [d["ip"] for d in got], "the API gives the same list"

# the watch: an event only when the list changes, a row without MAC by its address
events, alerts = [], []
watch = newdevicewatch.NewDeviceWatch(lambda: {}, events.append, lambda *a, **k: alerts.append((a, k)))
watch.set(got)
watch.set(got)
assert len(events) == 1 and events[0]["count"] == 3, events
watch.set(got[:2] + [{**plain, "ip": "192.168.60.30"}])
assert len(events) == 2, "another address without MAC: the list changed"

# the alert without MAC
newdevicewatch.settings.alerts_enabled = lambda: True
newdevicewatch.warn_new([newdevices.routed_entry({"mac": None, "ip": "192.168.60.7", "hostname": None, "first_seen": now, "network": "iot"})],
                        lambda message, key, **params: alerts.append((message, key, params)))
assert alerts == [("Nuovo dispositivo in rete: 192.168.60.7 (192.168.60.7) MAC -", "alert.new_device", {"label": "192.168.60.7", "ip": "192.168.60.7"})], alerts
print("check_routed_new: ok")
