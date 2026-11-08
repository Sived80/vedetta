"""The networks Vedetta looks at now: the abstraction in front of the places that today ask the host for its network (netutil.get_local_network).

The main network is derived from the host at every call (the interface chosen in iface, its address and mask): it is never written to disk and
nobody can change it. Networks written by the person do not exist yet (they come with the panel, in their own store): today the world is the main
network alone, so current() gives exactly what netutil.filter_local_ips allows (tests/check_networks_registry.py).
Not used by the app yet: the callers move here one at a time, each with a test that the result does not change."""
import ipaddress

from .. import netutil
from ..applog import logger
from .model import Network
from .scope import Scope

MAIN_ID = "main"


async def main() -> tuple[str, str]:
    """(network, own address) of the main network, as netutil.get_local_network gives it (and raising what it raises)."""
    return await netutil.get_local_network()


def main_interface() -> str:
    """The interface of the main network: the one netutil.get_local_network reads (iface.lan_iface, through netutil so that both always agree)."""
    return netutil.lan_iface()


def main_network(cidr: str) -> Network:
    """The main network as a Network: confirmed, reached through the host's own interface. Not checked by model.validate: it is what the host
    says, a /8 included (how much of it is asked is decided by scan/arpplan.py, not here)."""
    return Network(MAIN_ID, ipaddress.ip_network(cidr), frozenset({"direct"}), "full", "confirmed")


def on_link(ip: str) -> bool:
    """The address may be asked by ARP now, without reading the host: it is in the main network as last read (netutil.last_network,
    refreshed by the continuous ARP view). False while the network is not known yet (K14)."""
    cidr = netutil.last_network
    return bool(cidr) and scope_of(cidr).arp_targets([ip]) == [ip]


def scope_of(cidr: str) -> Scope:
    """The confirmed networks when the main one is `cidr` (already read): today the main one alone."""
    return Scope((main_network(cidr),))


async def current() -> Scope:
    """The confirmed networks, the main one first. Today: the main one alone."""
    cidr, _ = await main()
    return scope_of(cidr)


async def allowed(ips: list) -> list:
    """The addresses of `ips` that belong to a confirmed network, in the order given: today exactly netutil.filter_local_ips, the warning in the
    log included, and the same ValueError on a value that is not an address (its callers check first; tests/check_networks_registry.py)."""
    scope = await current()
    for ip in ips:
        ipaddress.ip_address(ip)
    kept = [ip for ip in ips if scope.network_of(ip) is not None]
    rejected = [ip for ip in ips if scope.network_of(ip) is None]
    if rejected:
        logger.warning("Scansione rifiutata, IP fuori dalla rete locale %s: %s", scope.networks[0].cidr, ", ".join(rejected))
    return kept
