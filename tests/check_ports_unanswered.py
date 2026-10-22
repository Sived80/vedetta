"""A deep search that finds no stable port at all on a device that had some (scan/rescan.py _hold_unanswered_ports). Seen on the exports of 22 Oct: a camera and an ESPHome device, scanned while the host disk was saturated by a backup (the
scans timed out or answered in half a second), were reported with every port "no longer open" and, at the next search, with the same ports "newly open": no port had changed, the device had not answered. The first time it happens
the old ports are kept and nothing is said (the card remembers it); the second time in a row it is taken as true. A partial answer is a real change. A device whose only ports are dynamic ones has nothing to hold."""
import asyncio
import os
import sys
import tempfile
import types

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import rescan  # noqa: E402

ALERTS: list = []
SAVED: list = []
rescan.state = types.SimpleNamespace(emit_alert=lambda text, key, **k: ALERTS.append((key, k["ports"])), refresh_device=None, _last_mac={})
rescan.devices_config.update_scan_info = lambda device_id, info: SAVED.append(dict(info))
rescan.history = types.SimpleNamespace(save_scan=lambda *a, **k: None)


def p(*numbers):
    return [{"label": str(n)} for n in numbers]


def scan(previous_ports, new_ports, unseen=0):
    """One deep search: the card had `previous_ports` (and `unseen` empty answers in a row), the scan found `new_ports`; what is saved and what is said."""
    ALERTS.clear(); SAVED.clear()
    previous = {"ports": p(*previous_ports), "scanned_at": 1.0}
    if unseen:
        previous["ports_unseen"] = unseen
    fields = {"mdns_name": "x", **({"ports": p(*new_ports)} if new_ports else {})}      # a card with some other clue but no port: the scan is not empty, so it reaches the saving
    asyncio.run(rescan._save_scan_and_alert_ports(previous, fields, {"id": "d1"}, 2.0, "10.0.0.5 (x)"))
    return SAVED[-1], list(ALERTS)


labels = lambda saved: [x["label"] for x in saved.get("ports", [])]  # noqa: E731

# --- the camera and the ESPHome case: stable ports before, none now -> held, silent, remembered
saved, alerts = scan([80, 554, 4567, 8000, 34567], [])
assert labels(saved) == ["80", "554", "4567", "8000", "34567"] and saved["ports_unseen"] == 1 and alerts == [], (saved, alerts)
saved, alerts = scan([80, 6053], [53691])        # only a dynamic port answered: no stable port at all
assert labels(saved) == ["80", "6053"] and saved["ports_unseen"] == 1 and alerts == [], (saved, alerts)

# --- and the next search that finds them again says nothing (no «new port» after the false closing)
saved, alerts = scan([80, 6053], [80, 6053], unseen=1)
assert labels(saved) == ["80", "6053"] and "ports_unseen" not in saved and alerts == [], (saved, alerts)

# --- the second empty answer in a row is true: the ports go, the closing is said, the counter goes
saved, alerts = scan([80, 6053], [], unseen=1)
assert not labels(saved) and "ports_unseen" not in saved and alerts == [("alert.port_closed", "80, 6053")], (saved, alerts)

# --- a partial answer is a real change: nothing is held, the missing ports are reported
saved, alerts = scan([80, 554, 8000], [80])
assert labels(saved) == ["80"] and "ports_unseen" not in saved and alerts == [("alert.port_closed", "554, 8000")], (saved, alerts)
saved, alerts = scan([80], [80, 8883])
assert alerts == [("alert.port_opened", "8883")]

# --- nothing to hold: a phone with only dynamic ports (they are never reported), a card with no ports at all
saved, alerts = scan([53691, 62078], [])
assert "ports_unseen" not in saved and alerts == [], (saved, alerts)
saved, alerts = scan([], [])
assert "ports_unseen" not in saved and alerts == []
print("check_ports_unanswered OK")
