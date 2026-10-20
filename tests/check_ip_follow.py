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
swapped = []


def fake_swap(id_a, id_b):
    swapped.append((id_a, id_b))
    return True


devices_config.swap_ips = fake_swap


async def go():
    s = DeviceState()
    alerts = []
    s.emit_alert = lambda msg, key, **p: alerts.append((key, p))
    s.trigger = lambda force=False, reason="": None
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




async def swap_case():
    """A PC took the address of a phone that left: the PC's card (offline at its old address) moves there, the phone's card takes the PC's old address. An online holder is never displaced."""
    moved.clear(); swapped.clear()
    cfgs = [{"id": "pc", "ip": "10.0.0.117"}, {"id": "ph", "ip": "10.0.0.116"}]
    devices_config.load_devices = lambda: [dict(c) for c in cfgs]
    s = DeviceState()
    alerts = []
    s.emit_alert = lambda msg, key, **p: alerts.append((key, p))
    s.trigger = lambda force=False, reason="": None
    s._last_mac = {"pc": "74:04:F1:CC:33:7D", "ph": "AA:BB:CC:00:00:01"}
    arp = {"10.0.0.116": {"mac": "74:04:f1:cc:33:7d"}}
    s.devices = {"pc": {"online": False, "name": "MSI"}, "ph": {"online": False, "name": "S23"}}
    await s.follow_ip_changes(arp)
    assert swapped == [("pc", "ph")] and not moved, (swapped, moved)
    assert len(alerts) == 1 and alerts[0][0] == "alert.ip_changed" and alerts[0][1]["old"] == "10.0.0.117" and alerts[0][1]["new"] == "10.0.0.116", alerts
    # the holder is online (it answers with its own MAC elsewhere): nothing is displaced
    swapped.clear(); alerts.clear()
    s.devices["ph"]["online"] = True
    await s.follow_ip_changes(arp)
    assert not swapped and not moved and not alerts, (swapped, moved, alerts)
    # the holder's own MAC is the one that answers: it is where it says it is
    s.devices["ph"]["online"] = False
    await s.follow_ip_changes({"10.0.0.116": {"mac": "aa:bb:cc:00:00:01"}})
    assert not swapped and not moved, (swapped, moved)


asyncio.run(go())
asyncio.run(swap_case())
print("TUTTO OK")
