"""Characterization of the quick search ("Search devices") before the work on more networks, where a row may come without a MAC (a device behind a router):
- run_initial sees the network through ARP only: arp-scan, the neighbours the system has just seen answer (REACHABLE) INSIDE the local network, the own host; a neighbour
  of another network (on a VLAN interface, or a stale entry) is never a host; every host has a MAC;
- _run_quick_scan returns the rows {ip, mac, hostname, already_added: False} of the hosts whose address has no card yet, in the order of the search, with the ignored ones
  left out and counted; the new-devices counter is realigned to the MACs seen.
Fake commands and a temporary data folder; private placeholder addresses.
    python tests/check_quick_scan_shape.py"""
import asyncio
import io
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import netutil  # noqa: E402
from app.routes import scan_routes  # noqa: E402
from app.scan import pipeline, scan_arp  # noqa: E402

OUT = {
    "arp-scan": "10.0.0.10\taa:bb:cc:00:00:0a\tMaker A\n10.0.0.11\taa:bb:cc:00:00:0b\t(Unknown)\n",
    "neigh": "10.0.0.12 lladdr aa:bb:cc:00:00:0c REACHABLE\n10.0.20.30 lladdr aa:bb:cc:00:00:1e REACHABLE\n10.0.0.13 lladdr aa:bb:cc:00:00:0d STALE\n",
    "addr": "3: lan9    inet 10.0.0.2/24 brd 10.0.0.255 scope global lan9\n",
}


class FakeProc:
    returncode = 0

    def __init__(self, out: str):
        self.out = out

    async def communicate(self, data=None):
        return self.out.encode(), b""


async def fake_exec(*args, **kwargs):
    key = "arp-scan" if args[0] == "arp-scan" else ("neigh" if "neigh" in args else "addr")
    return FakeProc(OUT[key])


netutil.asyncio.create_subprocess_exec = fake_exec
netutil.lan_iface = lambda: "lan9"
scan_arp.open = lambda *a, **k: io.StringIO("02:00:5e:00:00:02\n")

# 1) run_initial: ARP only, the local network only, every host with a MAC
hosts = asyncio.run(pipeline.run_initial())
assert [h["ip"] for h in hosts] == ["10.0.0.10", "10.0.0.11", "10.0.0.12", "10.0.0.2"], [h["ip"] for h in hosts]
assert all(h["mac"] for h in hosts) and all(h["ports"] == [] for h in hosts), hosts
assert {"ip", "mac", "hostname", "ports"} <= set(hosts[0]), hosts[0]

# 2) _run_quick_scan: shape of the rows, known addresses left out, ignored ones counted
scan_routes.devices_config.load_devices = lambda: [{"ip": "10.0.0.11"}]
scan_routes.blocklist.matches = lambda mac=None, ip=None, name=None: ip == "10.0.0.12"
SYNCED: list = []
scan_routes.newdevices.sync_present = lambda macs: SYNCED.append(set(macs))
scan_routes.newdevices.list_new = lambda: []
visible, ignored = asyncio.run(scan_routes._run_quick_scan())
assert [r["ip"] for r in visible] == ["10.0.0.10", "10.0.0.2"] and ignored == 1, (visible, ignored)
for row in visible:
    assert set(row) == {"ip", "mac", "hostname", "already_added"} and row["already_added"] is False and row["mac"], row
assert SYNCED == [{h["mac"] for h in hosts}], SYNCED

# 3) today a host always has a MAC: a row without one stops the search (the work on more networks will allow mac: null for the hosts behind a router)
async def no_mac():
    return [{"ip": "10.0.20.30", "hostname": None}]


pipeline.run_initial = no_mac
try:
    asyncio.run(scan_routes._run_quick_scan())
except KeyError:
    pass
else:
    raise AssertionError("a host without MAC is accepted: update this characterization on purpose")

print("check_quick_scan_shape: ok")
