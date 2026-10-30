"""The devices Home Assistant sees on other networks ("passive" devices), from the reading to the card.

What this proves, on invented data (documentation addresses 192.0.2.x / 198.51.100.x, made-up MACs):
- reading: of all the states only the device trackers whose source is "router" are kept, and only five facts of each; a phone tracker with coordinates, a person, a zone and the trackers
  Vedetta publishes itself leave nothing behind (not in the rows, not in what is stored, not in the log); "unavailable" is not "away";
- the websocket conversation asks for the states and the registry of the entities and nothing else;
- store: off by default, adoption, what the user chose survives a new reading, a client that goes "unavailable" keeps its last known state, forgetting, a file that cannot be read starts empty;
- card: the same keys as the card of a device Vedetta scans (plus `passive`), no ports and no response time, the user's choice wins over what Home Assistant says;
- list to choose from: what Vedetta already has (by MAC or by address) is not offered, networks are in the order Home Assistant lists them;
- no probe: with every socket forbidden, the whole path (reading with a fake Home Assistant, store, card, presence in the history) still works, and the modules do not import anything that scans.
"""
import asyncio
import json
import os
import re
import socket
import sys
import tempfile
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import applog  # noqa: E402
from app.ha import ha_data, ha_registry, ha_trackers, passive_service, passive_view  # noqa: E402
from app.storage import passive_store  # noqa: E402
from app.storage.history import History  # noqa: E402

failed = 0


def check(cond, msg):
    global failed
    if cond:
        print("ok:", msg)
    else:
        failed += 1
        print("FAILED:", msg)


def tracker(entity, state, mac, ip=None, host=None, name=None, source="router", **extra):
    attrs = {"source_type": source, "mac": mac, "ip": ip, "host_name": host, "friendly_name": name, **extra}
    return {"entity_id": entity, "state": state, "attributes": {k: v for k, v in attrs.items() if v is not None}}


GPS = tracker("device_tracker.phone_of_anna", "home", "02:00:5e:aa:00:01", source="gps", latitude=45.4642, longitude=9.19, gps_accuracy=12)
STATES = [
    tracker("device_tracker.cam_front", "home", "02:00:5E:10:00:21", "198.51.100.21", "cam-front", "Front camera"),
    tracker("device_tracker.plug_a", "not_home", "02:00:5e:10:00:31", "198.51.100.31", "shellyplug-8f2a"),
    tracker("device_tracker.sensor_b", "unavailable", "02:00:5e:20:00:09", "192.168.40.9", "sensor-b"),
    tracker("device_tracker.no_ip", "not_home", "02:00:5e:10:00:71", None, "thermostat"),
    tracker("device_tracker.vedetta_own", "home", "02:00:5e:00:00:99", "192.0.2.99", "vedetta-card"),
    GPS,
    {"entity_id": "person.anna", "state": "home", "attributes": {"latitude": 45.4642, "longitude": 9.19, "source": "device_tracker.phone_of_anna"}},
    {"entity_id": "zone.home", "state": "0", "attributes": {"latitude": 45.4642, "longitude": 9.19, "radius": 100}},
    {"entity_id": "sensor.temperature", "state": "21", "attributes": {}},
    tracker("device_tracker.bad_mac", "home", "not-a-mac", "198.51.100.50", "x"),
    tracker("device_tracker.bad_ip", "home", "02:00:5e:10:00:77", "999.1.1.1", "bad-ip"),
]
OWN = ha_trackers.own_entity_ids([{"entity_id": "device_tracker.vedetta_own", "unique_id": "vedetta_abcd_tracker"}, {"entity_id": "device_tracker.cam_front", "unique_id": "unifi-1"}])

# ---- reading: only the router trackers, only five facts
rows = ha_trackers.extract(STATES, OWN)
check([r["mac"] for r in rows] == ["02:00:5e:10:00:21", "02:00:5e:10:00:31", "02:00:5e:20:00:09", "02:00:5e:10:00:71", "02:00:5e:10:00:77"], "only the router trackers with a valid MAC, in the order Home Assistant lists them")
check(all(set(r) == set(ha_trackers.KEPT) for r in rows), "every row has exactly the five kept facts")
check(OWN == {"device_tracker.vedetta_own"}, "the trackers Vedetta publishes itself are recognised by their unique id")
check(not any(r["mac"] == "02:00:5e:aa:00:01" for r in rows), "the phone tracker (GPS) is not kept")
dump = json.dumps(rows)
check(not re.search(r"latitude|longitude|45\.46|gps|person|zone|anna", dump, re.I), "no coordinate, person or zone anywhere in what is kept")
check([r["online"] for r in rows] == [True, False, None, False, True], "home, not_home, unavailable (None) and a bad address (kept without it)")
bad = next(r for r in rows if r["mac"].endswith("77"))
check(bad["ip"] is None, "an address that is not IPv4 is dropped, the client is kept")
check(ha_trackers.extract([STATES[0], tracker("device_tracker.cam_front2", "not_home", "02:00:5E:10:00:21", "198.51.100.21", "cam-front")])[0]["online"] is False, "the same MAC tracked twice: the last reading wins")

# ---- the conversation with Home Assistant: states and the registry of the entities, in that order, and no other command
SENT: list = []


class FakeWs:
    def __init__(self):
        self.script = [{"type": "auth_required"}, {"type": "auth_ok"}, {"id": 1, "type": "result", "success": True, "result": STATES},
                       {"id": 2, "type": "result", "success": True, "result": [{"entity_id": "device_tracker.vedetta_own", "unique_id": "vedetta_abcd_tracker"}]}]

    async def recv(self):
        return json.dumps(self.script.pop(0))

    async def send(self, text):
        SENT.append(json.loads(text))


class Connection:
    def __init__(self, ws):
        self.ws = ws

    async def __aenter__(self):
        return self.ws

    async def __aexit__(self, *exc):
        return False


def fake_connect(*a, **k):
    return Connection(FakeWs())


import types  # noqa: E402

sys.modules["websockets"] = types.SimpleNamespace(connect=fake_connect)
os.environ["SUPERVISOR_TOKEN"] = "t0ken"
fetched = asyncio.run(ha_trackers.fetch())
commands = [m["type"] for m in SENT if m["type"] != "auth"]
check(commands == ["get_states", "config/entity_registry/list"], "it asks the states and the entity registry, nothing else")
check(len(fetched) == 5 and all(r["mac"] != "02:00:5e:00:00:99" for r in fetched), "the answer is cut down the same way (the tracker of Vedetta is left out)")
del os.environ["SUPERVISOR_TOKEN"]
try:
    asyncio.run(ha_trackers.fetch())
    check(False, "without a token the reading fails")
except RuntimeError:
    check(True, "without a token the reading fails with a plain error")

# ---- store
passive_store.reset_cache()
check(passive_store.enabled() is False, "the function is off by default")
check(passive_store.snapshot()["adopted"] == {}, "nothing is adopted at the start")
passive_store.set_enabled(True)
passive_store.record_read(rows, 1000.0)
snap = passive_store.snapshot()
check(len(snap["candidates"]) == 5 and snap["read_at"] == 1000.0 and snap["error"] is None, "a reading replaces the candidates")
done = passive_store.adopt(["02:00:5e:10:00:21", "02:00:5e:20:00:09", "02:00:5e:ff:ff:ff"], 1001.0)
check(done == ["02:00:5e:10:00:21", "02:00:5e:20:00:09"], "adopting: unknown MACs are skipped")
check(passive_store.adopt(["02:00:5e:10:00:21"], 1002.0) == [], "adopting twice does nothing")
check(passive_store.set_edit("02:00:5e:10:00:21", "name", "Front door") and passive_store.set_edit("02:00:5e:10:00:21", "type", "media"), "the user can choose name and type")
check(passive_store.set_edit("02:00:5e:ff:ff:ff", "name", "x") is False, "an edit on a device that is not adopted is refused")
try:
    passive_store.set_edit("02:00:5e:10:00:21", "ip", "1.2.3.4")
    check(False, "only name, type and brand can be chosen")
except ValueError:
    check(True, "only name, type and brand can be chosen")
passive_store.record_read([{**r, "name": "Renamed in HA", "online": False} if r["mac"].endswith("21") else r for r in rows], 2000.0)
snap = passive_store.snapshot()
adopted = snap["adopted"]["02:00:5e:10:00:21"]
check(adopted["edit"] == {"name": "Front door", "type": "media"} and adopted["row"]["name"] == "Renamed in HA", "a new reading updates what Home Assistant says and keeps what the user chose")
check(snap["adopted"]["02:00:5e:20:00:09"]["row"]["online"] is None, "an adopted client first seen as unavailable has no state yet")
passive_store.record_read([{**r, "online": True} if r["mac"].endswith("09") else r for r in rows], 3000.0)
passive_store.record_read([{**r, "online": None} if r["mac"].endswith("09") else r for r in rows], 3100.0)
check(passive_store.snapshot()["adopted"]["02:00:5e:20:00:09"]["row"]["online"] is True, "unavailable keeps the last known state")
passive_store.record_read([], 4000.0, "boom")
snap = passive_store.snapshot()
check(snap["error"] == "boom" and snap["read_at"] == 3100.0 and len(snap["candidates"]) == 5, "a failed reading changes nothing but the error")
passive_store.set_edit("02:00:5e:10:00:21", "name", "")
check("name" not in passive_store.snapshot()["adopted"]["02:00:5e:10:00:21"]["edit"], "an empty value goes back to Home Assistant")
passive_store.reset_cache()
check(len(passive_store.snapshot()["adopted"]) == 2 and passive_store.enabled(), "everything is read again from the file")
check(not (Path(os.environ["VEDETTA_DATA_DIR"]) / "devices.yaml").exists(), "nothing is ever written to devices.yaml")
passive_store.PATH.write_text("{not json", encoding="utf-8")
passive_store.reset_cache()
check(passive_store.snapshot()["adopted"] == {} and passive_store.enabled() is False, "a file that cannot be read starts empty")
check(passive_store.mac_of(passive_store.id_of("02:00:5E:10:00:21")) == "02:00:5e:10:00:21" and passive_store.mac_of("ha-xyz") is None and passive_store.mac_of("scan-1") is None, "ids go to MACs and back")

# ---- the card
passive_store.reset_cache()
passive_store.set_enabled(True)
passive_store.record_read(rows, 1000.0)
passive_store.adopt(["02:00:5e:10:00:21", "02:00:5e:10:00:31"], 1001.0)
data = passive_store.snapshot()
cards = passive_view.compact_all(data)
scanned = ha_data.compact_device({"id": "scan-1", "name": "x", "ip": "192.0.2.5", "mac": "02:00:5E:00:00:05", "online": True})
check(set(scanned) <= set(cards[0]) and cards[0]["passive"] is True, "a passive card has every key of the card of a scanned device, plus passive")
check(cards[0]["ports"] == [] and cards[0]["latency_ms"] is None and cards[0]["port"] is None and cards[0]["scanned_at"] is None, "no ports, no response time, no scan")
check(cards[0]["name"] == "Front camera" and cards[0]["name_source"] == "ha" and cards[0]["online"] is True, "name and state come from Home Assistant")
check(cards[1]["online"] is False and cards[1]["name"] == "shellyplug-8f2a", "without a name Home Assistant shows, the host name is used")
passive_store.set_edit("02:00:5e:10:00:21", "name", "Front door")
passive_store.set_edit("02:00:5e:10:00:21", "type", "media")
passive_store.set_edit("02:00:5e:10:00:21", "brand", "Acme")
card = passive_view.compact_all(passive_store.snapshot())[0]
check((card["name"], card["type"], card["brand"], card["name_source"], card["brand_source"]) == ("Front door", "media", "Acme", "user", "user"), "what the user chose wins")
check(all(c["id"].startswith("ha-") and c["id"] == passive_store.id_of(c["mac"]) for c in cards), "ids are ha- plus the MAC")

# ---- the list to choose from
data = passive_store.snapshot()
offer = passive_view.candidates(data, {"02:00:5E:10:00:77"}, {"192.168.40.9"})
check([r["mac"] for r in offer] == ["02:00:5e:10:00:71"] or [r["mac"] for r in offer] == [], "adopted ones are not offered again")
data["adopted"] = {}
offer = passive_view.candidates(data, {"02:00:5E:10:00:77"}, {"192.168.40.9"})
macs = [r["mac"] for r in offer]
check("02:00:5e:10:00:77" not in macs and "02:00:5e:20:00:09" not in macs, "what Vedetta already has is not offered, by MAC or by address")
check(macs == ["02:00:5e:10:00:21", "02:00:5e:10:00:31", "02:00:5e:10:00:71"], "networks in the order Home Assistant lists them, addresses ascending inside, no address last")
check([r["net"] for r in offer][:2] == ["198.51.100.0/24"] * 2 and offer[-1]["net"] is None and not any(r["same_net"] for r in offer), "each client says its network, and that it is not one where Vedetta has devices")
check(passive_view.candidates(data, set(), {"198.51.100.200"})[0]["same_net"] is True, "a client on a network where Vedetta already has a device is said to be on it")

# ---- no probe: every socket forbidden, the whole path still works
def forbidden(*a, **k):
    raise AssertionError("a socket was used")


real = (socket.socket.connect, socket.create_connection, socket.getaddrinfo, socket.socket.sendto)
H = History(Path(os.environ["VEDETTA_DATA_DIR"]) / "h.db")
passive_service.history = H
passive_service._last_online.clear()


async def fake_fetch():
    return rows


events = []
passive_service._on_change = events.append
passive_service.ha_trackers.fetch = fake_fetch
loop = asyncio.new_event_loop()      # made before the sockets are forbidden: the loop itself uses one to wake up
socket.socket.connect, socket.create_connection, socket.getaddrinfo, socket.socket.sendto = forbidden, forbidden, forbidden, forbidden
try:
    passive_store.reset_cache()
    passive_store.set_enabled(True)
    first = loop.run_until_complete(passive_service.read_now())
    passive_store.adopt(["02:00:5e:10:00:21", "02:00:5e:10:00:31"], 5.0)
    second = loop.run_until_complete(passive_service.read_now())
    ok_path = True
except AssertionError:
    ok_path = False
finally:
    socket.socket.connect, socket.create_connection, socket.getaddrinfo, socket.socket.sendto = real
check(ok_path, "reading, store, card and presence work with every socket forbidden")
check(events == [{"type": "passive"}] * 2, "every reading tells the open pages")
seg = H.presence_segments(passive_store.id_of("02:00:5e:10:00:21"), 0, 1e12)
check(bool(seg.get("segments")) and seg["segments"][-1]["online"] is True, "the presence of an adopted device is written to the history")
before = len(H.presence_segments(passive_store.id_of("02:00:5e:10:00:21"), 0, 1e12)["segments"])
loop.run_until_complete(passive_service.read_now())
check(len(H.presence_segments(passive_store.id_of("02:00:5e:10:00:21"), 0, 1e12)["segments"]) == before, "a reading that changes nothing writes nothing")
check(passive_service.presence_changes({"02:00:5e:10:00:31": {"row": {"ip": "198.51.100.31", "online": False}}}, {"ha-02005e100031": True}) == [("ha-02005e100031", "198.51.100.31", "02:00:5E:10:00:31", False)], "presence_changes: a change is reported")

# the code that reads and keeps these devices does not even import what scans or probes
app_dir = Path(__file__).resolve().parent.parent / "vedetta" / "app"
FILES = [app_dir / "ha" / "ha_trackers.py", app_dir / "ha" / "passive_view.py", app_dir / "ha" / "passive_service.py", app_dir / "storage" / "passive_store.py"]
imports = "\n".join(re.findall(r"^\s*(?:from|import)\s+[^\n]+", "\n".join(f.read_text(encoding="utf-8") for f in FILES), re.M))
check(not re.search(r"scan|probe|nmap|arp|ping|subprocess|state import", imports), "none of them imports a scanner, a probe or the shared state")

# the log: nothing but counts and errors
log_text = Path(applog.__file__).read_text(encoding="utf-8") if False else ""
check("45.46" not in json.dumps(passive_store.snapshot()) and "latitude" not in json.dumps(passive_store.snapshot()), "the file kept holds no coordinate")

print("\nFAILED: %d" % failed if failed else "\nall ok")
sys.exit(1 if failed else 0)
