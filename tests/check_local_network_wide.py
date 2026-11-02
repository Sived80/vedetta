"""The local network as the page gets it (Discussion #15: a /22 was shown as a /24): netutil keeps the network of its last reading, the roles that reach the page (event and summary) carry it, and
the list of the clients Home Assistant sees groups them by it. The export, which keeps the snapshot of the roles, does not get it. Before the first reading there is none, and the page keeps its /24. Fake `ip addr` output; documentation and private placeholder addresses."""
import asyncio
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import netutil  # noqa: E402
from app.recognition import roles  # noqa: E402
from app.routes import passive_routes  # noqa: E402


class FakeProc:
    def __init__(self, text: str):
        self.text = text

    async def communicate(self):
        return self.text.encode(), b""


def reading(text: str):
    async def fake(*args, **kwargs):
        return FakeProc(text)
    return fake


assert netutil.last_network is None and roles.page_view()["network"] is None, "before the first reading the page gets no network (and keeps its /24)"

netutil.asyncio.create_subprocess_exec = reading("2: eth0    inet 10.20.2.50/22 brd 10.20.3.255 scope global dynamic eth0\n")
assert asyncio.run(netutil.get_local_network()) == ("10.20.0.0/22", "10.20.2.50")
assert netutil.last_network == "10.20.0.0/22" and roles.page_view()["network"] == "10.20.0.0/22" and roles.event()["network"] == "10.20.0.0/22", roles.page_view()
assert "network" not in roles.snapshot(), "the export keeps the snapshot of the roles: no network in it"

data = {"enabled": True, "read_at": 1.0, "error": None, "adopted": {},
        "candidates": {"02:00:5e:10:00:21": {"mac": "02:00:5e:10:00:21", "ip": "10.20.1.7", "name": "a"}, "02:00:5e:10:00:31": {"mac": "02:00:5e:10:00:31", "ip": "10.20.3.9", "name": "b"},
                       "02:00:5e:10:00:41": {"mac": "02:00:5e:10:00:41", "ip": "192.168.40.5", "name": "c"}}}
nets = [(r["ip"], r["net"]) for r in passive_routes.payload(data)["candidates"]]
assert nets == [("10.20.1.7", "10.20.0.0/22"), ("10.20.3.9", "10.20.0.0/22"), ("192.168.40.5", "192.168.40.0/24")], nets

netutil.asyncio.create_subprocess_exec = reading("")
try:
    asyncio.run(netutil.get_local_network())
except Exception:
    pass
assert netutil.last_network == "10.20.0.0/22", "a reading that fails keeps the last network that was read"

print("check_local_network_wide: ok")
