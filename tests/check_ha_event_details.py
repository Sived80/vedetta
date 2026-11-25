"""The events on the bus of Home Assistant (app/ha/ha_notify.py event_data) carry, next to the keys of 1.0.2 (card, label, ip, and
minutes on a return), always the same four keys: brand, type (the group, as the MQTT "type"), kind (the finer type, as the MQTT
"kind") and reason (why a device is new: one of ha_notify.NEW_REASONS; null on a down or a back). A value Vedetta does not know is
null, never absent, so templates stay simple. The facts are taken when the event is born, from what is in memory
(sentinel_view.on_presence / on_new_device, newdevicewatch.warn_new): an event saved by an older version still gives every key.
Events stay off by default, and the export still masks the label and the address of the saved events.
    python tools/run_test.py check_ha_event_details.py"""
import json
import os
import sys
import tempfile

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import newdevicewatch, sentinel_view  # noqa: E402
from app.export.anonymize import Anonymizer  # noqa: E402
from app.ha import ha_data, ha_notify  # noqa: E402
from app.storage import settings  # noqa: E402

NEW_KEYS = {"brand", "type", "kind", "reason"}
AP = {"id": "ap1", "name": "Office Access Point", "ip": "192.0.2.10", "mac": "02:00:00:00:00:10", "brand": "Acmenet", "online": True}
TV = {"id": "tv1", "name": "Living Room TV", "ip": "192.0.2.11", "mac": "02:00:00:00:00:11", "online": True}
CONFIG = {"ap1": {"id": "ap1", "watch": "1"}, "tv1": {"id": "tv1", "watch": "1", "type_user": "pc"}}
ha_data.config_map = lambda: CONFIG
sent: list = []
sentinel_view.add_sender(sent.extend)

# 1) an event of 1.0.2 (saved before the update): the old keys exactly as before, the new ones null
OLD_BACK = {"kind": "back", "card": "nas", "params": {"label": "NAS", "ip": "192.0.2.5", "away_s": 1250}}
data = ha_notify.event_data(OLD_BACK)
assert {k: data[k] for k in ("card", "label", "ip", "minutes")} == {"card": "nas", "label": "NAS", "ip": "192.0.2.5", "minutes": 21}
assert {k: data[k] for k in NEW_KEYS} == dict.fromkeys(NEW_KEYS), data
assert set(data) == {"card", "label", "ip", "minutes"} | NEW_KEYS
OLD_DOWN = {"kind": "down", "card": "nas", "params": {"label": "NAS", "ip": "192.0.2.5"}}
assert set(ha_notify.event_data(OLD_DOWN)) == {"card", "label", "ip"} | NEW_KEYS, "minutes only on a return, as before"

# 2) a watched card goes down and comes back: brand, group and finer type of the card (the group chosen by hand wins)
for dev in (AP, TV):
    sentinel_view.on_presence({**dev, "online": False}, False, 100)
sentinel_view.after_cycle({"ap1": {**AP, "online": False}, "tv1": {**TV, "online": False}}, lambda *a, **k: None, now=500)
down = {ev["card"]: ha_notify.event_data(ev) for ev in sent if ev["kind"] == "down"}
assert down["ap1"] == {"card": "ap1", "label": "Office Access Point", "ip": "192.0.2.10", "brand": "Acmenet", "type": "router",
                       "kind": "accesspoint", "reason": None}, down["ap1"]
assert down["tv1"]["brand"] is None and down["tv1"]["type"] == "pc" and down["tv1"]["kind"] != "tv", down["tv1"]
sentinel_view.on_presence(AP, True, 900)
sentinel_view.after_cycle({"ap1": AP, "tv1": {**TV, "online": False}}, lambda *a, **k: None, now=901)
back = ha_notify.event_data(sent[-1])
assert back["minutes"] == 13 and (back["brand"], back["type"], back["kind"], back["reason"]) == ("Acmenet", "router", "accesspoint", None), back

# 3) new devices: why they are new, their brand and their type from what the watch already has
settings.update({"alerts": True})
LAN = {"mac": "02:00:00:00:00:20", "ip": "192.0.2.20", "vendor": None, "hostname": "attic-accesspoint", "first_seen": 1.0,
       "brand": None, "vendor_role": None}
ROUTED = {"mac": None, "ip": "198.51.100.7", "vendor": None, "hostname": None, "first_seen": 1.0, "network": "n1", "brand": None,
          "vendor_role": None}
newdevicewatch.warn_new([LAN, ROUTED], lambda *a, **k: None)
sentinel_view.after_cycle({}, lambda *a, **k: None, now=1000)
new = {ev["card"]: ha_notify.event_data(ev) for ev in sent if ev["kind"] == "new"}
assert new["02:00:00:00:00:20"] == {"card": "02:00:00:00:00:20", "label": "attic-accesspoint", "ip": "192.0.2.20", "brand": None,
                                    "type": "router", "kind": "accesspoint", "reason": "new_mac"}, new
assert new["198.51.100.7"]["reason"] == "new_behind_router" and new["198.51.100.7"]["type"] == "generic" and new["198.51.100.7"]["kind"] is None
assert set(ha_notify.NEW_REASONS) == {"new_mac", "new_behind_router"}
assert all(d["reason"] in ha_notify.NEW_REASONS for d in new.values())

# 4) the commands: the event carries the same data; off by default, nothing is fired
cmds = ha_notify.commands([sent[-1]], True, "", "en")
assert cmds == [{"type": "fire_event", "event_type": "vedetta_new_device", "event_data": ha_notify.event_data(sent[-1])}]
assert ha_notify.commands([sent[-1]], False, "", "en") == []
assert settings.sentinel_load()["ha_events"] is False
assert ha_notify.lines([sent[-1]], "en") == ["New device on the network: 198.51.100.7 (198.51.100.7)"], "the message text is unchanged"

# 5) privacy: the saved events go into the export masked as before (label and address), the device facts stay readable
saved = json.loads(sentinel_view.STORE.read_text(encoding="utf-8"))
anon = Anonymizer()
for dev in (AP, TV):
    anon.add_ip(dev["ip"])
    anon.add_device([dev["name"]])
anon.add_device([LAN["hostname"]])
text = json.dumps(anon.data(saved))
for secret in ("Office Access Point", "Living Room TV", "attic-accesspoint", "192.0.2.10", "192.0.2.20"):
    assert secret not in text, secret
assert '"kind": "accesspoint"' in text and '"brand": "Acmenet"' in text and '"reason": "new_mac"' in text
print("ok: brand, type, kind and reason in the events of Home Assistant")
