"""The health findings for the page (ha/health_view.py): off unless VEDETTA_HEALTH=shadow; a rule in shadow is judged and counted but never reaches the snapshot or the event; a rule that is shown reaches both once it is active; the summary counts by rule and state
and holds no address. The signals are handed in, nothing is sent to any device."""
import asyncio
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import health_view as hv  # noqa: E402
from app.health.engine import Engine  # noqa: E402
from app.health import matrix  # noqa: E402

NOW = 1_000_000.0
ROW = matrix.load()[0]
CONFLICT = {"conflicts": {"192.168.1.20": ["aa:bb:cc:00:00:01", "aa:bb:cc:00:00:02"]}}

# --- off by default; on only with the exact word
os.environ.pop("VEDETTA_HEALTH", None)
assert not hv.enabled()
os.environ["VEDETTA_HEALTH"] = "on"
assert not hv.enabled(), "only «shadow» turns it on"
os.environ["VEDETTA_HEALTH"] = "shadow"
assert hv.enabled()

# --- a rule in shadow: judged, counted, never shown
shadow = Engine([dict(ROW, status="shadow")])
assert hv.judge_once(shadow, CONFLICT, 0) == [] and hv.judge_once(shadow, CONFLICT, 10) == [], "shadow changes are not handed to the page"
assert hv.snapshot(shadow) == [], "a finding in shadow is never in the snapshot"
assert hv.summary(shadow) == {"H20": {"active": 1}}, hv.summary(shadow)

# --- a rule that is shown: the active finding reaches the snapshot, without addresses
shown = Engine([dict(ROW, status="active")])
assert [c.change for c in hv.judge_once(shown, CONFLICT, 0)] == ["opened"]
assert [c.change for c in hv.judge_once(shown, CONFLICT, 10)] == ["raised"]
snap = hv.snapshot(shown)
assert len(snap) == 1 and snap[0]["rule"] == "H20" and snap[0]["subject"] == "lan" and snap[0]["severity"] == "warning", snap
assert "192.168" not in repr(snap) and "aa:bb" not in repr(snap) and "192.168" not in repr(hv.summary(shown))

# --- the drops come from the presence history of the last day
read = hv.read_signals(NOW, presence=lambda since: [("a", True, since + 10), ("a", False, since + 20), ("b", True, since + 30)], latency=lambda now: {"gateway": [(NOW - 60, 0.5)]})
assert read["now"] == NOW and read["drops"] == {"a": [NOW - hv.SIGNAL_WINDOW_S + 20]} and read["devices"] == 2, read

# --- the latency of the gateway: the device is the one that has the address of the default route; no route or no such device, nothing
got = hv.gateway_latency(NOW, gateway=lambda: "10.0.0.1", devices=lambda: [{"id": "x", "ip": "10.0.0.9"}, {"id": "gw", "ip": "10.0.0.1"}], points=lambda device, a, b: [(a, 0.5), (b, 0.6)] if device == "gw" else [])
assert got == {"gateway": [(NOW - hv.LATENCY_WINDOW_S, 0.5), (NOW, 0.6)]}, got
assert hv.gateway_latency(NOW, gateway=lambda: None, devices=lambda: [{"id": "gw", "ip": "10.0.0.1"}], points=lambda *a: [(1, 1)]) == {}, "no default route"
assert hv.gateway_latency(NOW, gateway=lambda: "10.0.0.1", devices=lambda: [{"id": "x", "ip": "10.0.0.9"}], points=lambda *a: [(1, 1)]) == {}, "the gateway is not a card"
assert hv.read_signals(NOW, presence=lambda since: [], latency=lambda now: {"gateway": [(1, 2)]})["latency"] == {"gateway": [(1, 2)]}

# --- the signals come from the scan view, copied (the judge cannot change the scan)
hv.scanner.arp_conflicts.clear()
hv.scanner.arp_conflicts["10.0.0.5"] = ["m1", "m2"]
read = hv.read_signals(NOW, presence=lambda since: [], latency=lambda now: {})
read["conflicts"]["10.0.0.5"].append("m3")
assert hv.scanner.arp_conflicts["10.0.0.5"] == ["m1", "m2"], "the signals are a copy"
hv.scanner.arp_conflicts.clear()

# --- start does nothing when it is off, and stop is safe
os.environ.pop("VEDETTA_HEALTH")


async def lifecycle():
    hv.start()
    assert hv._task is None, "off: no background task"
    await hv.stop()

asyncio.run(lifecycle())
print("check_health_view OK")
