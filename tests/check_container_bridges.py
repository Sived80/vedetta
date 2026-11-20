"""The host's own container bridges are never a network behind the router (networks/legacy.py container_networks): known by the NAME
of the interface (docker*, br-<id>, veth*, hassio, podman*, cni-podman*), not by an address range, because a runtime takes its
ranges from the same private blocks a real LAN uses. A user network of Docker in 192.168.200.0/24 or 172.20.0.0/16 used to pass
the fixed ranges and be proposed; a plain br0 with a real LAN on it must stay admissible.
    python tests/check_container_bridges.py"""
import os
import sys
import tempfile

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.networks import legacy, registry  # noqa: E402
from app.networks.scope import Scope  # noqa: E402

HOST = {"interfaces": [
    {"name": "lo", "ipv4": [{"address": "127.0.0.1", "prefix": 8}]},
    {"name": "enp1s0", "ipv4": [{"address": "192.168.1.100", "prefix": 24}]},
    {"name": "br0", "ipv4": [{"address": "192.168.50.1", "prefix": 24}]},              # an ordinary bridge: a real LAN
    {"name": "docker0", "ipv4": [{"address": "172.17.0.1", "prefix": 16}]},
    {"name": "br-3f2a9c1d", "ipv4": [{"address": "192.168.200.1", "prefix": 24}]},     # a user network of Docker in 192.168.x
    {"name": "br-77aa", "ipv4": [{"address": "172.20.0.1", "prefix": 16}]},
    {"name": "hassio", "ipv4": [{"address": "172.30.32.1", "prefix": 23}]},
    {"name": "veth12ab", "ipv4": []},
    {"name": "podman0", "ipv4": [{"address": "10.88.0.1", "prefix": 16}]},
    {"name": "cni-podman1", "ipv4": [{"address": "10.89.0.1", "prefix": 24}]},
    {"name": "dockerbad", "ipv4": [{"address": "x", "prefix": 24}, {"prefix": 24}]},    # junk is skipped, not fatal
]}

blocked = legacy.container_networks(HOST)
assert sorted(map(str, blocked)) == sorted(["172.17.0.0/16", "192.168.200.0/24", "172.20.0.0/16", "172.30.32.0/23", "10.88.0.0/16", "10.89.0.0/24"]), blocked

# 1) the addresses of a container bridge are not admissible, the real LANs are
for ip in ("192.168.200.7", "172.20.3.4", "10.88.0.9", "10.89.0.2"):
    assert legacy.admissible(ip) and not legacy.admissible(ip, blocked), ip          # passed before, blocked now
for ip in ("192.168.50.20", "192.168.20.5", "10.1.2.3"):
    assert legacy.admissible(ip, blocked), ip
assert not legacy.admissible("8.8.8.8", blocked) and not legacy.admissible("nonsense", blocked)

# 2) no proposal for a container bridge, a proposal for the real LAN behind br0
scope = Scope(())
got = [p["cidr"] for p in legacy.proposals(["192.168.200.7", "192.168.50.20", "172.20.3.4"], scope, blocked)]
assert got == ["192.168.50.0/24"], got
assert legacy.container_networks({}) == () and legacy.container_networks({"interfaces": None}) == ()

# 3) the registry reads the host at most every CONTAINERS_TTL_S
reads = []
registry.host_read.read_host = lambda: (reads.append(1), HOST)[1]
registry._containers.update({"at": None, "nets": ()})
for _ in range(50):
    assert registry._host_containers() == blocked
assert len(reads) == 1, reads
registry._containers["at"] -= registry.CONTAINERS_TTL_S
registry._host_containers()
assert len(reads) == 2
print("check_container_bridges: ok")
