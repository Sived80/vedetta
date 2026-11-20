"""1.0 step P11 (decisions 1A, 2A): routedwatch, the ping sweep of the networks behind the router, with a spy on what leaves.
- only the confirmed networks seen through the router are swept: a paused one, one reached through the host's own interface and the main
  one never; the excluded range never; one ping per address and nothing else leaves (no connection, no socket, no process: no port, no ARP,
  no name request);
- the first sweep is the starting point (listed as new, no alert); a device never seen afterwards is alerted once, in the words of the home
  network with "MAC -" when the MAC is unknown, and never again; with the trackers of Home Assistant the alert carries the MAC;
- the button «Search devices» sweeps too and lists the addresses that answered and are not a card;
- the loop waits while the periodic check is paused, and stops at once when cancelled; the counts for the export.
Fake ping, fake state, temporary data folder, invented private addresses only.
    python tests/check_routed_sweep.py"""
import asyncio
import os
import socket
import sys
import tempfile
import time

DATA = tempfile.mkdtemp()
os.environ["VEDETTA_DATA_DIR"] = DATA
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import maclayer, netutil, newdevicewatch, routedwatch  # noqa: E402
from app.networks import registry  # noqa: E402
from app.routes import scan_routes  # noqa: E402
from app.scan import latency  # noqa: E402
from app.storage import devices_config, network_store, newdevices, passive_store  # noqa: E402
from app.storage.history import history  # noqa: E402

registry.ROUTE_FILE = os.path.join(DATA, "no-route-file")   # the fake network, not the routes of this computer
netutil.last_network = "192.168.50.0/24"
MAIN = registry.main_network("192.168.50.0/24")
network_store.add({"id": "iot", "cidr": "192.168.60.0/28", "via": ["routed"], "state": "confirmed", "exclude": ["192.168.60.10-192.168.60.12"]}, MAIN)
network_store.add({"id": "cams", "cidr": "192.168.70.0/28", "via": ["routed"], "state": "paused"}, MAIN)
network_store.add({"id": "lab", "cidr": "192.168.80.0/28", "via": ["direct"], "state": "confirmed"}, MAIN)
devices_config.add_devices([{"ip": "192.168.60.3", "name": "card"}])

ANSWER = {"192.168.60.2", "192.168.60.3", "192.168.60.5"}
PINGED: list = []
TOUCHED: list = []


async def fake_icmp(ip, timeout):
    PINGED.append(ip)
    return 1.0 if ip in ANSWER else None


async def trip_async(*a, **k):
    TOUCHED.append(("async", a[:2]))
    raise OSError("spy")


def trip_socket(self, *a, **k):
    TOUCHED.append(("socket", a[:1]))
    raise OSError("spy")


class FakeState:
    def __init__(self):
        self.alerts, self.lists, self.paused = [], [], None

    def emit_alert(self, message, key, **params):
        self.alerts.append((message, key, params))

    def set_new_devices(self, devices):
        self.lists.append(devices)

    def paused_remaining(self):
        return self.paused


latency.icmp_ms = fake_icmp
fake = routedwatch.state = FakeState()
newdevicewatch.settings.alerts_enabled = lambda: True


async def sweep():
    PINGED.clear()
    real = socket.socket.connect, socket.socket.connect_ex, socket.socket.sendto, asyncio.open_connection, asyncio.create_subprocess_exec
    socket.socket.connect = socket.socket.connect_ex = socket.socket.sendto = trip_socket       # once the loop exists: it connects a socket pair of its own
    asyncio.open_connection = asyncio.create_subprocess_exec = trip_async
    try:
        return await routedwatch.sweep()
    finally:
        socket.socket.connect, socket.socket.connect_ex, socket.socket.sendto, asyncio.open_connection, asyncio.create_subprocess_exec = real


SWEPT = sorted("192.168.60.%d" % i for i in range(1, 15) if not 10 <= i <= 12)

# 1) the first sweep: only the pings of the confirmed network behind the router, the starting point
listed = asyncio.run(sweep())
assert sorted(PINGED) == SWEPT and not TOUCHED, (PINGED, TOUCHED)
assert fake.alerts == [] and fake.lists == [], "the starting point: no alert"
rows = {r["ip"]: r for r in history.routed_rows("iot")}
assert sorted(rows) == sorted(ANSWER) and all(r["mac"] is None for r in rows.values()), rows
assert [ip for ip, r in sorted(rows.items()) if r["status"] == "new"] == ["192.168.60.2", "192.168.60.5"], "listed as new, the card never"
assert sorted(r["ip"] for r in listed) == ["192.168.60.2", "192.168.60.5"] and all(r["mac"] is None for r in listed), "the button lists what answered, never a card"

# 2) a device never seen: alerted once, "MAC -"
ANSWER.add("192.168.60.7")
asyncio.run(sweep())
assert [(m, k) for m, k, _ in fake.alerts] == [("Nuovo dispositivo in rete: 192.168.60.7 (192.168.60.7) MAC -", "alert.new_device")], fake.alerts
assert fake.alerts[0][2] == {"label": "192.168.60.7", "ip": "192.168.60.7"} and len(fake.lists) == 1, fake.alerts
assert history.routed_rows("iot") and {r["ip"]: r for r in history.routed_rows("iot")}["192.168.60.7"]["status"] == "new"
asyncio.run(sweep())
assert len(fake.alerts) == 1 and not TOUCHED, "never a second alert"
listed_new = {d["ip"]: d for d in newdevices.list_new()}
assert sorted(listed_new) == ["192.168.60.2", "192.168.60.5", "192.168.60.7"] and listed_new["192.168.60.7"]["mac"] is None, listed_new
assert "192.168.60.4" not in listed_new, "an address that never answers is never listed"

# 3) with the trackers of Home Assistant the MAC is known
passive_store.set_enabled(True)
passive_store.record_read([{"mac": "02:00:5e:60:00:08", "ip": "192.168.60.8", "host": "plug", "name": None, "online": True, "since": 1.0}], time.time())
ANSWER.add("192.168.60.8")
asyncio.run(sweep())
assert fake.alerts[-1][0] == "Nuovo dispositivo in rete: plug (192.168.60.8) MAC 02:00:5E:60:00:08", fake.alerts
assert {r["ip"]: r for r in history.routed_rows("iot")}["192.168.60.8"]["mac"] == "02:00:5E:60:00:08"


# 4) the button sweeps too
async def no_hosts():
    return []


async def no_pass(*a, **k):
    return None


scan_routes.pipeline.run_initial = no_hosts
maclayer.observe_pass = no_pass
ANSWER.add("192.168.60.9")
visible, ignored = asyncio.run(scan_routes._run_quick_scan())
assert "192.168.60.9" in [h["ip"] for h in visible] and "192.168.60.3" not in [h["ip"] for h in visible], visible
assert fake.alerts[-1][0].startswith("Nuovo dispositivo in rete: 192.168.60.9 ") and len(fake.alerts) == 3, fake.alerts

# 5) the counts
got = routedwatch.counts()
assert {k: got[k] for k in ("networks", "sweeps", "asked", "new")} == {"networks": 1, "sweeps": 5, "asked": 5 * len(SWEPT), "new": 3}, got
assert got["answered"] == 3 + 4 + 4 + 5 + 6 and got["with_mac"] == 2 and got["seconds"] >= 0, got


# 6) the loop: nothing while paused, and it ends at once when cancelled
async def loop_case():
    routedwatch.FIRST_SWEEP_S, routedwatch.ROUTED_SWEEP_S = 0, 0.01
    fake.paused = float("inf")
    PINGED.clear()
    routedwatch.start()
    await asyncio.sleep(0.1)
    assert PINGED == [], "paused: no sweep"
    started = time.monotonic()
    await routedwatch.stop()
    assert time.monotonic() - started < 1 and routedwatch._task.done()


asyncio.run(loop_case())
print("check_routed_sweep: ok")
