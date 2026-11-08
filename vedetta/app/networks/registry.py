"""The networks Vedetta looks at now: the abstraction in front of the places that today ask the host for its network (netutil.get_local_network).

The main network is derived from the host at every call (the interface chosen in iface, its address and mask): it is never written to disk and
nobody can change it. Networks written by the person do not exist yet (they come with the panel, in their own store): today the world is the main
network alone, so current() gives exactly what netutil.filter_local_ips allows (tests/check_networks_registry.py).
Not used by the app yet: the callers move here one at a time, each with a test that the result does not change."""
import ipaddress

from .. import netutil
from .model import Network
from .scope import Scope

MAIN_ID = "main"


async def main() -> tuple[str, str]:
    """(network, own address) of the main network, as netutil.get_local_network gives it (and raising what it raises)."""
    return await netutil.get_local_network()


def main_network(cidr: str) -> Network:
    """The main network as a Network: confirmed, reached through the host's own interface. Not checked by model.validate: it is what the host
    says, a /8 included (how much of it is asked is decided by scan/arpplan.py, not here)."""
    return Network(MAIN_ID, ipaddress.ip_network(cidr), frozenset({"direct"}), "full", "confirmed")


async def current() -> Scope:
    """The confirmed networks, the main one first. Today: the main one alone."""
    cidr, _ = await main()
    return Scope((main_network(cidr),))
