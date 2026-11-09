"""Spy test (K9b): in the check cycle a card whose address may not be touched gets nothing: no adapter call, no response-time measure.
A card with a public address, one in a paused network and one in a proposed network (the grace period: touched as before) next to a card of
the main network. The cycle reads the cards, proposes the networks, marks the cards, and the adapter and the response-time measure see only
the cards that may be touched. Invented addresses only (192.168.50-99.x, documentation range).
    python tests/check_off_limits_not_probed.py"""
import asyncio
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import netutil, state as state_mod, state_cycle  # noqa: E402
from app.networks import registry  # noqa: E402
from app.scan import latency, probe  # noqa: E402
from app.storage import devices_config, network_store  # noqa: E402

registry.ROUTE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "no-route-file")
netutil.last_network = "192.168.50.0/24"
MAIN = registry.main_network("192.168.50.0/24")
network_store.add({"id": "old", "cidr": "192.168.70.0/24", "via": ["routed"], "state": "paused"}, MAIN)
CARDS = [{"id": "main", "ip": "192.168.50.10", "adapter": "generic"}, {"id": "pub", "ip": "203.0.113.9", "adapter": "generic"},
         {"id": "paused", "ip": "192.168.70.4", "adapter": "generic"}, {"id": "grace", "ip": "192.168.60.4", "adapter": "generic"}]
devices_config.load_devices = lambda: [dict(c) for c in CARDS]
ASKED, MEASURED = [], []


async def spy_adapter(ip, port):
    ASKED.append(ip)
    return {"online": True}


async def spy_measure(targets):
    MEASURED.extend(ip for _, ip, _ in targets)
    return {}


async def no_arp(_max_age):
    return {}


probe.ADAPTERS["generic"] = spy_adapter
latency.measure_many = spy_measure
st = state_mod.DeviceState()
st._arp_by_ip = no_arp
st._apply = lambda *a, **k: None
asyncio.new_event_loop().run_until_complete(state_cycle.poll_once(st))

assert sorted(ASKED) == ["192.168.50.10", "192.168.60.4"], ASKED
assert sorted(MEASURED) == ["192.168.50.10", "192.168.60.4"], MEASURED
assert [str(n.cidr) for n in network_store.load(MAIN)] == ["192.168.70.0/24", "192.168.60.0/24"], "the card outside every network is proposed"
assert "off_limits" not in str(devices_config.load_devices()), "the mark is never saved"
print("check_off_limits_not_probed: ok")
