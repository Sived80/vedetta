"""The routes of the devices Home Assistant sees, through the real HTTP layer with Home Assistant faked: the switch, the reading (refused while the function is off), the list, the adoption,
the card in /api/ha/devices next to the scanned ones, the history of a card, and the changes (rename, brand, type, remove) that arrive on the routes of the other devices.
A passive device never reaches devices.yaml, and the flag and the sharing do not exist for it."""
import os
import sys
import tempfile
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.ha import passive_service  # noqa: E402
from app.routes import device_routes, passive_routes  # noqa: E402
from app.routes import ha as routes_ha  # noqa: E402
from app.state import state  # noqa: E402
from app.storage import devices_config, passive_store  # noqa: E402
from app.storage.history import History  # noqa: E402

failed = 0


def check(cond, msg):
    global failed
    if cond:
        print("ok:", msg)
    else:
        failed += 1
        print("FAILED:", msg)


tmp = Path(os.environ["VEDETTA_DATA_DIR"])
devices_config.DEVICES_PATH = tmp / "devices.yaml"
devices_config.CONFIG_DIR = tmp
H = History(tmp / "vedetta.db")
passive_service.history = H
routes_ha.history = H
ROWS = [
    {"mac": "02:00:5e:10:00:21", "ip": "198.51.100.21", "host": "cam-front", "name": "Front camera", "online": True},
    {"mac": "02:00:5e:10:00:31", "ip": "198.51.100.31", "host": "plug-a", "name": None, "online": False},
    {"mac": "02:00:5e:00:00:05", "ip": "192.0.2.5", "host": "mine", "name": None, "online": True},
]


async def fake_fetch():
    return ROWS


passive_service.ha_trackers.fetch = fake_fetch
state.devices["scan-1"] = {"id": "scan-1", "name": "Mine", "ip": "192.0.2.5", "mac": "02:00:5E:00:00:05", "online": True}
app = FastAPI()
app.include_router(passive_routes.router)
app.include_router(device_routes.router)
app.include_router(routes_ha.router)
client = TestClient(app)

r = client.get("/api/ha/networks").json()
check(r["enabled"] is False and r["candidates"] == [] and r["adopted"] == 0, "off at the start, nothing to choose from")
check(client.post("/api/ha/networks/read").status_code == 409, "reading is refused while the function is off")
check(client.post("/api/ha/networks/enabled", json={"enabled": "yes"}).status_code == 400, "the switch wants true or false")
check(client.post("/api/ha/networks/enabled", json={"enabled": True}).json()["enabled"] is True, "the switch turns on")
r = client.post("/api/ha/networks/read").json()
check([c["mac"] for c in r["candidates"]] == ["02:00:5e:10:00:21", "02:00:5e:10:00:31"], "the list leaves out what Vedetta already has (by MAC and by address)")
check(all(c["net"] == "198.51.100.0/24" for c in r["candidates"]), "each client says its network")
check(client.post("/api/ha/networks/adopt", json={"macs": "x"}).status_code == 400, "adopt wants a list")
r = client.post("/api/ha/networks/adopt", json={"macs": ["02:00:5E:10:00:21", "nonsense", "02:00:5e:77:77:77"]}).json()
check(r["done"] == 1 and r["adopted"] == 1 and [c["mac"] for c in r["candidates"]] == ["02:00:5e:10:00:31"], "adopting: the right one, the others skipped, the list shrinks")

devs = client.get("/api/ha/devices").json()["devices"]
ids = [d["id"] for d in devs]
check(ids == ["scan-1", "ha-02005e100021"] or set(ids) == {"scan-1", "ha-02005e100021"}, "the card sits next to the scanned ones in /api/ha/devices")
card = next(d for d in devs if d["id"] == "ha-02005e100021")
check(card["passive"] is True and card["online"] is True and card["ports"] == [], "a passive card, online, no ports")
check("passive" not in next(d for d in devs if d["id"] == "scan-1"), "the scanned card is not marked")

hist = client.get("/api/ha/history/ha-02005e100021")
check(hist.status_code == 200 and hist.json()["segments"], "the history of the card answers, with the presence written at the adoption")
check(client.get("/api/ha/history/ha-02005e100031").status_code == 404, "no history for a device that is not adopted")
check("ha-02005e100021" in client.get("/api/ha/history").json()["devices"], "the history of all includes the adopted ones")

check(client.post("/api/devices/ha-02005e100021/rename", json={"name": "Front door", "mobile": True}).status_code == 200, "rename goes to the store")
check(client.post("/api/devices/ha-02005e100021/override", json={"brand": "Acme", "type": "media", "ha_share": True, "focus": True}).status_code == 200, "brand and type go to the store")
card = next(d for d in client.get("/api/ha/devices").json()["devices"] if d["id"] == "ha-02005e100021")
check((card["name"], card["brand"], card["type"], card["ha_share"], card["focus"]) == ("Front door", "Acme", "media", False, False), "what the user chose is on the card; sharing and the flag are ignored")
check(client.post("/api/devices/ha-02005e100021/override", json={"type": "toaster"}).status_code == 400, "an unknown type is refused")
check(client.post("/api/devices/ha-02005e100031/rename", json={"name": "x"}).status_code == 404, "a device that is not adopted is not found")
check(client.post("/api/devices/ha-02005e100021/override", json={"brand": None, "type": None}).status_code == 200, "empty goes back to Home Assistant")
check(not (tmp / "devices.yaml").exists(), "none of this touched devices.yaml")

check(client.delete("/api/devices/ha-02005e100021?ignore=true").status_code == 200 and passive_store.snapshot()["adopted"] == {}, "removing takes it off the page")
r = client.get("/api/ha/networks").json()
check([c["mac"] for c in r["candidates"]] == ["02:00:5e:10:00:21", "02:00:5e:10:00:31"], "a removed one is offered again while Home Assistant sees it")
check(client.delete("/api/devices/ha-02005e100021").status_code == 404, "removing it twice is not found")

print("\nFAILED: %d" % failed if failed else "\nall ok")
sys.exit(1 if failed else 0)
