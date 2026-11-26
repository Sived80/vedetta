"""Presence held by Home Assistant (1.0.3): a phone asleep (Doze) stays on the Wi-Fi but does not answer ARP or ping for long stretches, while the
router integration of Home Assistant still has it. What this proves, on one real DeviceState whose network is faked (invented values only):
  - a MOBILE card that does not answer and whose MAC a router tracker of Home Assistant says "home" stays online, held by Home Assistant (the
    card says so in one line, the history records it present, so no "down" alert can start: those come from the presence transitions);
  - "not_home" -> offline as usual; "unavailable" -> today's rule (offline after the tolerance);
  - never a source: the tracker Vedetta publishes itself by MQTT (a loop), a GPS tracker (the person is in the home zone, not the phone on the
    network), a Bluetooth tracker; a card that is not mobile is never held;
  - the load on Home Assistant: nothing is asked when no mobile card is silent, at most one reading a minute otherwise, and none at all when the
    function "devices seen by Home Assistant" already reads every minute (its fresh reading is used; a stale one is not);
  - the refresh of a single card holds it too;
  - the switch in the menu (setting "phone_hold_ha", on by default): off, a silent phone goes offline by the usual rule, a card already held
    included, and Home Assistant is not read at all (neither asked nor the reading of the passive function).
Home Assistant is a fake websocket; no packet leaves."""
import asyncio
import json
import os
import sys
import tempfile
import time
import types
from pathlib import Path

import yaml

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import netutil, state as state_mod, state_cycle  # noqa: E402
from app.ha import ha_data  # noqa: E402
from app.scan import latency, presence, probe  # noqa: E402
from app.storage import devices_config, passive_store, settings  # noqa: E402
from app.networks import registry as _routes  # noqa: E402
_routes.ROUTE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "no-route-file")

failed = 0


def check(cond, msg):
    global failed
    print(("ok: " if cond else "FAILED: ") + msg)
    failed += 0 if cond else 1


NET = "192.0.2.0/24"
M_PHONE, M_PRINTER = "02:00:00:00:31:01", "02:00:00:00:31:02"
tmp = Path(tempfile.mkdtemp())
devices_config.DEVICES_PATH = tmp / "devices.yaml"
CARDS = [{"id": "phone", "ip": "192.0.2.31", "seq": 1, "name": "Phone of Test"}, {"id": "printer", "ip": "192.0.2.32", "seq": 2, "name": "Printer"}]
devices_config.DEVICES_PATH.write_text(yaml.safe_dump({"devices": CARDS}), encoding="utf-8")
netutil.last_network = NET


async def fake_net():
    """The faked main network, also for the cycle: on Linux the real `ip` command would give the runner's own network instead."""
    netutil.last_network, netutil.last_own = NET, "192.0.2.1"
    return NET, "192.0.2.1"


netutil.get_local_network = fake_net
os.environ["SUPERVISOR_TOKEN"] = "t0ken"


# --- a fake Home Assistant: the states of this case and the entity registry, counted
def tracker(entity, state, mac, source="router"):
    return {"entity_id": entity, "state": state, "attributes": {"source_type": source, "mac": mac, "friendly_name": entity}}


OWN_REGISTRY = [{"entity_id": "device_tracker.phone_of_test", "unique_id": "vedetta_phone_tracker", "platform": "mqtt"},
                {"entity_id": "device_tracker.router_client_1", "unique_id": "router-1", "platform": "routerint"}]
HA = {"states": [], "connects": 0}


class FakeWs:
    def __init__(self):
        self.script = [{"type": "auth_required"}, {"type": "auth_ok"}, {"id": 1, "type": "result", "success": True, "result": HA["states"]},
                       {"id": 2, "type": "result", "success": True, "result": OWN_REGISTRY}]

    async def recv(self):
        return json.dumps(self.script.pop(0))

    async def send(self, text):
        assert json.loads(text)["type"] in ("auth", "get_states", "config/entity_registry/list"), text


class Connection:
    async def __aenter__(self):
        HA["connects"] += 1
        return FakeWs()

    async def __aexit__(self, *exc):
        return False


sys.modules["websockets"] = types.SimpleNamespace(connect=lambda *a, **k: Connection())


# --- the network: who answers in this cycle
ANSWERS: set = set()


async def fake_probe(config, arp_task):
    table = {"192.0.2.31": {"mac": M_PHONE}, "192.0.2.32": {"mac": M_PRINTER}}
    res = await presence.complete_with_arp({"online": False}, config, config["ip"], arp_task)
    mobile = config["id"] == "phone"
    return {"id": config["id"], **res, "is_mobile": mobile, "mac_known": table[config["ip"]]["mac"], "extra": {}}


async def no_latency(targets):
    return {}


st = state_mod.DeviceState()
RECORDED: list = []


async def arp(max_age):
    table = {"192.0.2.31": {"mac": M_PHONE}, "192.0.2.32": {"mac": M_PRINTER}}
    t = time.time()
    st._view.mem = {ip: (t + 0.001, h) for ip, h in table.items() if ip in ANSWERS}
    return {ip: h for ip, h in table.items() if ip in ANSWERS}


async def nothing(*a):
    return None

probe.probe_device = fake_probe
latency.measure_many = no_latency
st._arp_by_ip = arp
st._save_latency = nothing
st._miss_limit = lambda: 1                    # the strictest tolerance: one miss is offline
st._record_presence = lambda result, online, ts: RECORDED.append((result["id"], online))
st._shadow = lambda *a: None


def fresh():
    """The reading of Home Assistant is kept for a minute: each case starts from a new one (the module did not exist before 1.0.3)."""
    mod = sys.modules.get("app.ha.tracker_hold")
    if mod is not None:
        mod.forget()


def cycle(answers, states=None, new_reading=True):
    if new_reading:
        fresh()
    ANSWERS.clear()
    ANSWERS.update(answers)
    if states is not None:
        HA["states"] = states
    RECORDED.clear()
    asyncio.run(st.poll_once())


def phone():
    return st.devices["phone"]


BOTH = {"192.0.2.31", "192.0.2.32"}
HOME = [tracker("device_tracker.router_client_1", "home", M_PHONE.upper()), tracker("device_tracker.router_client_2", "home", M_PRINTER)]

# 1) both answer: online, nothing is asked of Home Assistant (no mobile card is silent)
cycle(BOTH, HOME)
check(phone()["online"] and st.devices["printer"]["online"], "both answer: online")
check(HA["connects"] == 0, "nobody silent: Home Assistant is not asked (%d readings)" % HA["connects"])

# 2) both silent, the router tracker says home for both: the phone is held, the printer is not
cycle(set())
check(phone()["online"], "a silent phone that the router tracker says home stays online")
check(phone().get("presence_held") == "ha", "it says the presence is held by Home Assistant: %r" % phone().get("presence_held"))
check(("phone", False) not in RECORDED, "the history records no drop of the held phone (so no 'down' alert): %r" % RECORDED)
check(("phone", True) in RECORDED, "the history records the held phone present: %r" % RECORDED)
check(phone().get("mac") == M_PHONE, "the held card keeps what it observed when it answered (its MAC)")
row = [a for a in ha_data.compact_device(phone())["attrs"] if a["key"] == "presence_held"]
check(len(row) == 1 and row[0]["value"] and row[0]["label"], "the card tells it in one line: %r" % row)
check(not st.devices["printer"]["online"], "a card that is not mobile is never held by a tracker")
check(HA["connects"] == 1, "one reading for the cycle: %d" % HA["connects"])

# 3) the same in the next cycle (within the minute): no new reading
cycle(set(), new_reading=False)
check(phone()["online"] and HA["connects"] == 1, "at most one reading a minute: %d" % HA["connects"])

# 4) the tracker says not_home: offline as usual
cycle(set(), [tracker("device_tracker.router_client_1", "not_home", M_PHONE)])
check(not phone()["online"] and ("phone", False) in RECORDED, "not_home: offline as usual")
check(not phone().get("presence_held"), "no more held")

# 5) it answers again: online by itself, not held
cycle(BOTH)
check(phone()["online"] and not phone().get("presence_held"), "answering again: online by itself, not held")
check(not [a for a in ha_data.compact_device(phone())["attrs"] if a["key"] == "presence_held"], "and the card no longer tells it")

# 6) unavailable / unknown / no tracker at all: the rule of today (offline after the tolerance)
for name, states in (("unavailable", [tracker("device_tracker.router_client_1", "unavailable", M_PHONE)]),
                     ("unknown", [tracker("device_tracker.router_client_1", "unknown", M_PHONE)]), ("no tracker", [])):
    cycle(BOTH)
    cycle(set(), states)
    check(not phone()["online"], "%s: the rule of today, offline" % name)

# 7) never a source: Vedetta's own MQTT tracker, a GPS tracker, a Bluetooth tracker, a zone other than home
for name, states in (("Vedetta's own MQTT tracker", [tracker("device_tracker.phone_of_test", "home", M_PHONE)]),
                     ("a GPS tracker", [tracker("device_tracker.phone_gps", "home", M_PHONE, source="gps")]),
                     ("a Bluetooth tracker", [tracker("device_tracker.phone_ble", "home", M_PHONE, source="bluetooth_le")]),
                     ("another zone", [tracker("device_tracker.router_client_1", "office", M_PHONE)])):
    cycle(BOTH)
    cycle(set(), states)
    check(not phone()["online"], "%s says home: not used, offline" % name)
# the control of the first one: the same tracker, without Vedetta's unique id in the registry, would hold it (so the case above is not empty)
OWN_REGISTRY[0]["unique_id"] = "router-9"
cycle(BOTH)
cycle(set(), [tracker("device_tracker.phone_of_test", "home", M_PHONE)])
check(phone()["online"], "control: the same tracker not made by Vedetta holds it")
OWN_REGISTRY[0]["unique_id"] = "vedetta_phone_tracker"

# 8) Home Assistant cannot be read (an error): the rule of today, and the cycle goes on
cycle(BOTH)
sys.modules["websockets"] = types.SimpleNamespace(connect=lambda *a, **k: (_ for _ in ()).throw(OSError("refused")))
cycle(set(), HOME)
check(not phone()["online"], "Home Assistant unreachable: the rule of today")
sys.modules["websockets"] = types.SimpleNamespace(connect=lambda *a, **k: Connection())

# 9) the function "devices seen by Home Assistant" is on: its reading of every minute is used, nothing more is asked
passive_store.set_enabled(True)
passive_store.record_read([{"mac": M_PHONE, "ip": None, "host": None, "name": None, "online": True, "since": None}], time.time())
cycle(BOTH)
before = HA["connects"]
cycle(set(), [])
check(phone()["online"] and phone().get("presence_held") == "ha", "with the passive function on, its fresh reading holds the phone")
check(HA["connects"] == before, "and Home Assistant is not asked again (%d readings)" % (HA["connects"] - before))
passive_store.record_read([{"mac": M_PHONE, "ip": None, "host": None, "name": None, "online": True, "since": None}], time.time() - 600)
cycle(BOTH)
cycle(set(), [])
check(not phone()["online"], "a reading of 10 minutes ago is not used")
passive_store.set_enabled(False)


# 10) the refresh of a single card holds it too
async def refresh():
    st._measure = no_latency_one
    await st.refresh_device("phone")


async def no_latency_one(config):
    return None

cycle(BOTH)
fresh()
ANSWERS.clear()
HA["states"] = HOME
asyncio.run(refresh())
check(phone()["online"] and phone().get("presence_held") == "ha", "the refresh of one card: held too")

# 11) the switch of the menu: on by default; off, nothing is held and Home Assistant is not read at all
check(settings.load().get("phone_hold_ha") is True, "the function is on by default: %r" % settings.load().get("phone_hold_ha"))
cycle(BOTH)
cycle(set(), HOME)
check(phone()["online"] and phone().get("presence_held") == "ha", "switch on: the silent phone is held")
settings.update({"phone_hold_ha": False})
before = HA["connects"]
cycle(set(), HOME)
check(not phone()["online"] and ("phone", False) in RECORDED, "switch off: the phone held before goes offline by the usual rule: %r" % RECORDED)
check(not phone().get("presence_held"), "switch off: no more held")
check(HA["connects"] == before, "switch off: Home Assistant is not asked (%d readings)" % (HA["connects"] - before))
SNAPSHOTS = []
real_snapshot = passive_store.snapshot
passive_store.snapshot = lambda: SNAPSHOTS.append(1) or real_snapshot()
passive_store.set_enabled(True)
passive_store.record_read([{"mac": M_PHONE, "ip": None, "host": None, "name": None, "online": True, "since": None}], time.time())
cycle(BOTH)
cycle(set(), [])
check(not phone()["online"] and not SNAPSHOTS, "switch off: the fresh reading of the passive function is not used either (%d reads)" % len(SNAPSHOTS))
passive_store.set_enabled(False)
passive_store.snapshot = real_snapshot
settings.update({"phone_hold_ha": True, "group_order": []})
cycle(BOTH)
cycle(set(), HOME)
check(phone()["online"] and phone().get("presence_held") == "ha", "switch on again: held again")

print("ALL OK" if not failed else "%d FAILED" % failed)
sys.exit(1 if failed else 0)
