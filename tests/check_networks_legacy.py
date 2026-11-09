"""The cards outside the main network (networks/legacy.py, K12) and the addresses that may not be touched (registry.mark_off_limits, may_add: K8, K9).
1) admissible: private IPv4 outside the containers' networks only; 2) proposals: one network "proposed" per /24, behind the router, in the
order of the cards, never for an address already in a network (paused included); 3) registry.propose stores them once, and a proposal that
does not fit is said once in the log; 4) mark_off_limits: a public address, a container's or one in a paused network is marked (and
touch_policy then touches nothing), a proposed network is touched as before, a main network in a provider's shared range is touched,
nothing is marked before the main network is read; 5) may_add follows the same rule.
Invented addresses only (10.x, 192.168.50-99.x, documentation and shared ranges).
    python tests/check_networks_legacy.py"""
import os
import sys
import tempfile

DATA = tempfile.mkdtemp()
os.environ["VEDETTA_DATA_DIR"] = DATA
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import netutil  # noqa: E402
from app.networks import legacy, registry  # noqa: E402
from app.scan import touch_policy  # noqa: E402
from app.storage import network_store as store  # noqa: E402

registry.ROUTE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "no-route-file")
LOGS: list = []
registry.logger.info = lambda msg, *a: LOGS.append(msg % a)

# 1) admissible
for ip in ("10.1.2.3", "172.16.0.9", "192.168.60.4"):
    assert legacy.admissible(ip), ip
for ip in ("203.0.113.9", "8.8.8.8", "127.0.0.1", "169.254.1.1", "172.30.32.2", "172.17.0.3", "100.64.1.1", "not-an-ip", None, "::1"):
    assert not legacy.admissible(ip), ip

# 2) proposals
netutil.last_network = "192.168.50.0/24"
scope = registry.scope_of("192.168.50.0/24")
ips = ["192.168.50.5", "192.168.60.9", "203.0.113.9", "192.168.60.20", "10.9.20.4", "127.0.0.1"]
got = legacy.proposals(ips, scope)
assert got == [{"id": "p192-168-60", "cidr": "192.168.60.0/24", "via": ["routed"], "touch": "presence", "state": "proposed"},
               {"id": "p10-9-20", "cidr": "10.9.20.0/24", "via": ["routed"], "touch": "presence", "state": "proposed"}], got

# 3) propose
assert [str(n.cidr) for n in registry.propose(ips)] == ["192.168.60.0/24", "10.9.20.0/24"]
assert registry.propose(ips) == []                                    # stored once
assert legacy.proposals(ips, registry.scope_of("192.168.50.0/24")) == []
netutil.last_network = "192.168.50.0/25"                              # a main network that a /24 proposal would overlap
LOGS.clear()
registry.propose(["192.168.50.200"])
registry.propose(["192.168.50.200"])
assert sum("non proposta" in m for m in LOGS) == 1, LOGS

# 4) mark_off_limits
netutil.last_network = "192.168.50.0/24"
store.change("p10-9-20", {"state": "paused"}, registry.main_network("192.168.50.0/24"))
cards = [{"id": i, "ip": ip} for i, ip in enumerate(["192.168.50.5", "192.168.60.9", "10.9.20.4", "203.0.113.9", "172.30.32.2", "192.168.70.1"])]
marked = registry.mark_off_limits(cards)
assert [bool(d.get(touch_policy.OFF_LIMITS)) for d in marked] == [False, False, True, True, True, False], marked
assert not any(touch_policy.OFF_LIMITS in d for d in cards)          # the cards themselves are not changed (never saved)
assert [touch_policy.may_touch(d) for d in marked] == [True, True, False, False, False, True]
netutil.last_network = "100.64.0.0/24"                                # the main network in a provider's shared range: touched
assert not registry.mark_off_limits([{"id": 1, "ip": "100.64.0.7"}])[0].get(touch_policy.OFF_LIMITS)
netutil.last_network = None
assert registry.mark_off_limits(cards) == cards

# 5) may_add
netutil.last_network = "192.168.50.0/24"
assert registry.may_add("192.168.50.7") and registry.may_add("192.168.60.7") and registry.may_add("192.168.80.7")
assert not registry.may_add("203.0.113.9") and not registry.may_add("10.9.20.7") and not registry.may_add("127.0.0.1")
print("check_networks_legacy: ok")
