"""Phones with randomized (private) MACs: a card that rotates its address counts as a phone, a MAC lent by a repeater
does not count, and two cards of the same phone are merged only when it is clear."""
import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.storage import devices_config, history as history_mod
from app.recognition import identity  # noqa: E402
from app.storage.history import History  # noqa: E402
from app import state as state_mod  # noqa: E402

now = time.time()
H = History(Path(tempfile.mkdtemp()) / "t.db")
hour = 3600

# --- private MACs: counted per card, a global MAC and a MAC shared by several cards are not
for did, mac, ts in [("ph", "9a:42:31:00:00:01", now - 5 * hour), ("ph", "5a:8b:71:00:00:02", now - 4 * hour),
                     ("pc", "f0:18:98:00:00:03", now - 5 * hour), ("pc", "f0:18:98:00:00:04", now - 4 * hour),      # new network card: global MACs
                     ("a", "4e:3a:fd:00:00:05", now - 3 * hour), ("b", "4e:3a:fd:00:00:05", now - 3 * hour),       # lent by a repeater
                     ("one", "3a:00:00:00:00:06", now - 3 * hour)]:
    H.record_presence(did, "10.0.0.9", mac, True, ts)
counts = H.private_mac_counts(now - 7 * 86400)
assert counts == {"ph": 2, "one": 1}, counts

# --- the mobile score uses it, but a single private MAC or a replaced network card is not enough
base = dict(mac="9a:42:31:00:00:01", name_is_mobile=False, has_ports=None)
assert identity.mobile_assess(**base, mac_changes=2)["mobile"] and identity.mobile_assess(**base, mac_changes=2)["reason"] == "MAC privati diversi"
assert not identity.mobile_assess(**base, mac_changes=1)["mobile"]
assert not identity.mobile_assess(mac="f0:18:98:00:00:03", name_is_mobile=False, has_ports=None, mac_changes=0)["mobile"]
assert identity.mobile_assess(**base, mac_changes=2)["threshold"] == 3

# --- overlap and first seen
H.record_presence("x", None, None, True, now - 10 * hour)
H.record_presence("x", None, None, False, now - 6 * hour)
H.record_presence("y", None, None, True, now - 7 * hour)
H.record_presence("y", None, None, False, now - 3 * hour)
overlap = H.online_overlap("x", "y", now - 24 * hour, now)
assert abs(overlap - hour) < 5, overlap
assert H.online_overlap("x", "ph", now - 24 * hour, now) == 0
assert set(H.first_presence(["x", "y", "nobody"])) == {"x", "y"}
H.reassign_device("y", "x")
assert H.first_presence(["y"]) == {} and abs(H.first_presence(["x"])["x"] - (now - 10 * hour)) < 5

# --- merging, with the history and the configuration replaced by fakes
state_mod.history = H
configs = []
log = []


def fake_remove(device_id):
    before = len(configs)
    configs[:] = [c for c in configs if c["id"] != device_id]
    log.append(("remove", device_id))
    return len(configs) != before


def fake_update_ip(device_id, new_ip):
    if any(c["ip"] == new_ip for c in configs):
        return None
    c = next(c for c in configs if c["id"] == device_id)
    old, c["ip"] = c["ip"], new_ip
    log.append(("ip", device_id, new_ip))
    return old


devices_config.load_devices = lambda: [dict(c) for c in configs]
devices_config.remove_device = fake_remove
devices_config.update_ip = fake_update_ip
devices_config.update_scan_info = lambda i, s: log.append(("scan", i)) or True


def setup(entries):
    """entries: id, ip, name, online, first_seen_hours_ago, [(online_from_h, online_to_h)...]"""
    global H
    H = History(Path(tempfile.mkdtemp()) / "t2.db")
    state_mod.history = H
    configs.clear()
    log.clear()
    s = state_mod.DeviceState()
    alerts = []
    s.emit_alert = lambda msg, key, **p: alerts.append((key, p))
    s.trigger = lambda force=False: None
    s.devices = {}
    for did, ip, name, online, spans in entries:
        configs.append({"id": did, "ip": ip, "name": name, "scan_info": {}})
        s.devices[did] = {"id": did, "ip": ip, "name": name, "online": online, "is_mobile": True}
        for a, b in spans:
            H.record_presence(did, ip, None, True, now - a * hour)
            H.record_presence(did, ip, None, False, now - b * hour)
        if online:
            H.record_presence(did, ip, None, True, now - 0.2 * hour)
    return s, alerts


# two cards, same distinctive name, the old one offline, the new one online, never together: merged into the old one
s, alerts = setup([("old", "10.0.0.115", "Telefono di Luca", False, [(30, 2)]), ("new", "10.0.0.114", "telefono di luca", True, [])])
asyncio.run(s.merge_duplicate_phones())
assert "new" not in s.devices and "old" in s.devices and [c["id"] for c in configs] == ["old"], (s.devices.keys(), configs)
assert configs[0]["ip"] == "10.0.0.114" and ("remove", "new") in log and ("ip", "old", "10.0.0.114") in log, log
assert H.first_presence(["new"]) == {} and "old" in H.first_presence(["old"])
assert [a[0] for a in alerts] == ["alert.duplicate_merged"] and alerts[0][1]["new"] == "10.0.0.114", alerts

# the older card is the one online: it keeps its address, the offline ghost goes
s, alerts = setup([("old", "10.0.0.20", "Tablet cucina Anna", True, [(30, 2)]), ("new", "10.0.0.21", "Tablet cucina Anna", False, [(1.5, 1.0)])])
asyncio.run(s.merge_duplicate_phones())
assert list(s.devices) == ["old"] and configs[0]["ip"] == "10.0.0.20" and not any(x[0] == "ip" for x in log), (s.devices, log)

# not clear: online together for a long time (two phones with the same name), three cards, a generic name, both offline
s, _ = setup([("a", "10.0.0.30", "Telefono di Luca", True, [(30, 2)]), ("b", "10.0.0.31", "Telefono di Luca", True, [(20, 2)])])
asyncio.run(s.merge_duplicate_phones())
assert set(s.devices) == {"a", "b"}, "online together: two phones"
s, _ = setup([("a", "10.0.0.30", "Telefono di Luca", False, [(30, 20)]), ("b", "10.0.0.31", "Telefono di Luca", False, [(10, 5)]),
              ("c", "10.0.0.32", "Telefono di Luca", True, [])])
asyncio.run(s.merge_duplicate_phones())
assert set(s.devices) == {"a", "b", "c"}, "three cards: ambiguous"
s, _ = setup([("a", "10.0.0.30", "iPhone", False, [(30, 20)]), ("b", "10.0.0.31", "iPhone", True, [])])
asyncio.run(s.merge_duplicate_phones())
assert set(s.devices) == {"a", "b"}, "a bare iPhone is not a name"
s, _ = setup([("a", "10.0.0.30", "10.0.0.30", False, [(30, 20)]), ("b", "10.0.0.31", "10.0.0.31", True, [])])
asyncio.run(s.merge_duplicate_phones())
assert set(s.devices) == {"a", "b"}, "the IP is not a name"
s, _ = setup([("a", "10.0.0.30", "Telefono di Luca", False, [(30, 20)]), ("b", "10.0.0.31", "Telefono di Luca", False, [(10, 5)])])
asyncio.run(s.merge_duplicate_phones())
assert set(s.devices) == {"a", "b"}, "both offline: nothing to count, nothing done"
s, _ = setup([("a", "10.0.0.30", "Telefono di Luca", False, [(30, 20)]), ("b", "10.0.0.31", "Telefono di Luca", True, [])])
s.devices["b"]["is_mobile"] = False
asyncio.run(s.merge_duplicate_phones())
assert set(s.devices) == {"a", "b"}, "only mobile cards are merged"
print("TUTTO OK")
