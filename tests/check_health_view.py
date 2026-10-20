"""The health findings for the page (ha/health_view.py): on unless VEDETTA_HEALTH=off; a rule in shadow is judged and counted but never reaches the snapshot or the event; a rule that is shown reaches both once it is active; the summary counts by rule and state
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

# --- on by default (the judge runs in shadow, it sends nothing); off only with an explicit word
os.environ.pop("VEDETTA_HEALTH", None)
assert hv.enabled(), "the judge runs unless it is switched off"
os.environ["VEDETTA_HEALTH"] = "shadow"
assert hv.enabled()
for word in ("off", "OFF", " 0 ", "no", "false"):
    os.environ["VEDETTA_HEALTH"] = word
    assert not hv.enabled(), word
os.environ["VEDETTA_HEALTH"] = "shadow"

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

# --- the page: every active finding, the ones in shadow included (the page that asks is the debug one), with the names and addresses resolved from the cards
hv.scanner.arp_conflicts["10.0.0.5"] = ["aa:bb:cc:00:00:01", "aa:bb:cc:00:00:02"]
cards = [{"id": "a", "name": "Stampante", "ip": "10.0.0.5", "mac": "AA:BB:CC:00:00:01"}]
sh = Engine([dict(ROW, status="shadow")])
hv.judge_once(sh, CONFLICT, 0)
hv.judge_once(sh, CONFLICT, 10)
got = hv.page(sh, devices=lambda: cards, gateway=lambda: None)
assert len(got) == 1 and got[0]["id"] == "H20:10.0.0.5" and got[0]["shadow"] is True and got[0]["tile"] == "addr", got
assert got[0]["devs"][0] == {"id": "a", "name": "Stampante", "ip": "10.0.0.5"} and got[0]["devs"][1]["mac"] == "aa:bb:cc:00:00:02", got[0]["devs"]
assert hv.page(None) == [] and hv.snapshot(sh) == [], "no engine, nothing; and the snapshot of the event still hides the shadow"
hv.scanner.arp_conflicts.clear()

# --- the route of the page: it says whether the judge is running and hands over the entries; with no judge, an empty list
from app.routes import ha as routes_ha  # noqa: E402
assert not hv.running()
assert asyncio.run(routes_ha.api_ha_health()) == {"running": False, "findings": []}
hv._engine = sh
assert hv.running() and asyncio.run(routes_ha.api_ha_health())["running"] is True
hv._engine = None

# --- start does nothing when it is switched off, and stop is safe
os.environ["VEDETTA_HEALTH"] = "off"


async def lifecycle():
    hv.start()
    assert hv._task is None, "off: no background task"
    await hv.stop()

asyncio.run(lifecycle())
print("check_health_view OK")
