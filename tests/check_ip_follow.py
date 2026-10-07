"""An offline device whose MAC answers at another free IP follows the new address."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.storage import devices_config  # noqa: E402
from app.state import DeviceState  # noqa: E402

configs = [{"id": "a", "ip": "10.0.0.5", "name": "10.0.0.5"}, {"id": "b", "ip": "10.0.0.6"}, {"id": "c", "ip": "10.0.0.7"}]
moved = []


def fake_update(device_id, new_ip):
    moved.append((device_id, new_ip))
    old = next(c["ip"] for c in configs if c["id"] == device_id)
    return old


devices_config.load_devices = lambda: [dict(c) for c in configs]
devices_config.update_ip = fake_update


async def go():
    s = DeviceState()
    alerts = []
    s.emit_alert = lambda msg, key, **p: alerts.append((key, p))
    s.trigger = lambda force=False: None
    s.devices = {"a": {"online": False, "name": "Telefono"}, "b": {"online": False}, "c": {"online": True}}
    s._last_mac = {"a": "AA:BB:CC:00:00:01", "b": "AA:BB:CC:00:00:02", "c": "AA:BB:CC:00:00:03"}
    arp = {
        "10.0.0.50": {"mac": "aa:bb:cc:00:00:01"},                                  # a: new IP, unique
        "10.0.0.60": {"mac": "AA:BB:CC:00:00:02"}, "10.0.0.61": {"mac": "AA:BB:CC:00:00:02"},  # b: ambiguous
        "10.0.0.7": {"mac": "AA:BB:CC:00:00:03"},                                   # c: online
    }
    await s.follow_ip_changes(arp)
    assert moved == [("a", "10.0.0.50")], moved
    assert len(alerts) == 1 and alerts[0][0] == "alert.ip_changed" and alerts[0][1]["new"] == "10.0.0.50", alerts
    # without ARP nothing is done; with an IP already assigned to others it is not touched
    moved.clear()
    await s.follow_ip_changes({})
    await s.follow_ip_changes({"10.0.0.7": {"mac": "AA:BB:CC:00:00:01"}})
    assert not moved, moved
    # MAC shared by a repeater (the same MAC on two IPs, one already configured): not followed.
    s.devices["a"]["online"] = False
    await s.follow_ip_changes({"10.0.0.6": {"mac": "AA:BB:CC:00:00:01"}, "10.0.0.90": {"mac": "AA:BB:CC:00:00:01"}})
    assert not moved, moved


asyncio.run(go())
print("TUTTO OK")
