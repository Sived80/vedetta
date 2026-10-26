"""One phone with a private MAC that changed address twice while a repeater answered ARP for it must end up on ONE card.
The timelines are those of a real export (23 Oct 2026, 7 days of presence), with fake names, addresses and MACs and the times as hours before now:
a phone card (old) that moved away from its address and a second card (new) that took it, same model name, never online together,
with the MAC of a repeater showing up at the address a few times. Only the merge of the two cards is checked here."""
import asyncio
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import identity_upkeep  # noqa: E402
from app import state as state_mod  # noqa: E402
from app.storage import devices_config  # noqa: E402
from app.storage.history import History  # noqa: E402

HOUR = 3600
NAME = "Phone-14"       # the model name that the phone gives to DHCP: distinctive, not personal

# (address, MAC, online, hours before now); the repeater is 4e:..:02, the phone is c6:..:01
OLD = [
    ("10.0.0.18", "f6:00:00:00:00:03", 0, 69.10), ("10.0.0.18", "c6:00:00:00:00:01", 1, 27.71), ("10.0.0.18", None, 0, 26.83),
    ("10.0.0.18", "c6:00:00:00:00:01", 1, 26.68), ("10.0.0.18", None, 0, 25.78), ("10.0.0.18", "c6:00:00:00:00:01", 1, 23.31),
    ("10.0.0.18", "c6:00:00:00:00:01", 0, 15.23), ("10.0.0.18", "c6:00:00:00:00:01", 1, 15.19), ("10.0.0.18", None, 0, 15.05),
]
NEW = [
    ("10.0.0.20", "c6:00:00:00:00:01", 0, 40.41), ("10.0.0.18", "c6:00:00:00:00:01", 1, 15.02), ("10.0.0.18", "4e:00:00:00:00:02", 0, 9.99),
    ("10.0.0.18", "4e:00:00:00:00:02", 1, 9.96), ("10.0.0.18", "c6:00:00:00:00:01", 0, 9.06), ("10.0.0.18", "c6:00:00:00:00:01", 1, 9.01),
    ("10.0.0.18", "c6:00:00:00:00:01", 0, 7.68), ("10.0.0.18", "c6:00:00:00:00:01", 1, 7.64), ("10.0.0.18", None, 0, 7.35),
    ("10.0.0.18", "c6:00:00:00:00:01", 1, 6.78), ("10.0.0.18", None, 0, 5.83), ("10.0.0.18", "c6:00:00:00:00:01", 1, 5.54),
    ("10.0.0.18", "c6:00:00:00:00:01", 0, 5.48), ("10.0.0.18", "c6:00:00:00:00:01", 1, 3.17),
]

now = time.time()
H = History(Path(tempfile.mkdtemp()) / "t.db")
state_mod.history = identity_upkeep.history = H
configs = [{"id": "old", "ip": "10.0.0.20", "name": NAME, "scan_info": {}}, {"id": "new", "ip": "10.0.0.18", "name": NAME, "scan_info": {}}]
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
devices_config.update_scan_info = lambda i, s: True

for device_id, events in (("old", OLD), ("new", NEW)):
    for ip, mac, online, hours_ago in events:
        H.record_presence(device_id, ip, mac, bool(online), now - hours_ago * HOUR)

s = state_mod.DeviceState()
alerts = []
s.emit_alert = lambda msg, key, **p: alerts.append((key, p))
s.trigger = lambda force=False, reason="": None
s.devices = {"old": {"id": "old", "ip": "10.0.0.20", "name": NAME, "online": False, "is_mobile": True},
             "new": {"id": "new", "ip": "10.0.0.18", "name": NAME, "online": True, "is_mobile": True}}

overlap = H.online_overlap("old", "new", now - 7 * 86400, now)
assert overlap == 0, f"the two cards were never online together, got {overlap} s"
asyncio.run(s.merge_duplicate_phones())
assert list(s.devices) == ["old"], (list(s.devices), s.merge_report, log)
assert configs[0]["ip"] == "10.0.0.18" and [a[0] for a in alerts] == ["alert.duplicate_merged"], (configs, alerts)
# --- a pair that is NOT merged because both cards were online together says so in the log, with the seconds, once (not at every cycle)
records = []


class Catch(logging.Handler):
    def emit(self, record):
        records.append(record.getMessage())


logging.getLogger("dashboard").addHandler(Catch())
logging.getLogger("dashboard").setLevel(logging.INFO)
H2 = History(Path(tempfile.mkdtemp()) / "t2.db")
state_mod.history = identity_upkeep.history = H2
for device_id in ("a", "b"):
    H2.record_presence(device_id, "10.0.0.9", None, True, now - 5 * HOUR)
    H2.record_presence(device_id, "10.0.0.9", None, False, now - 2 * HOUR)
configs[:] = [{"id": "a", "ip": "10.0.0.30", "name": NAME, "scan_info": {}}, {"id": "b", "ip": "10.0.0.31", "name": NAME, "scan_info": {}}]
s.devices = {i: {"id": i, "ip": ip, "name": NAME, "online": i == "b", "is_mobile": True} for i, ip in (("a", "10.0.0.30"), ("b", "10.0.0.31"))}
for _ in range(3):
    asyncio.run(s.merge_duplicate_phones())
assert set(s.devices) == {"a", "b"} and s.merge_report["online_together"] == 1, s.merge_report
kept = [m for m in records if "online together" in m]
assert len(kept) == 1 and "10800" in kept[0] and NAME not in kept[0], records       # 3 hours = 10800 s; no name in the log
# and it tells when each card was first seen (hours ago, older first) and whether each is online now: who it is and where the overlap can come from
assert "first seen 5.0 h and 5.0 h ago" in kept[0] and "online now: no, yes" in kept[0], kept[0]
print("TUTTO OK")
