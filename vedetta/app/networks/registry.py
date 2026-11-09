"""The networks Vedetta looks at now: the abstraction in front of the places that today ask the host for its network (netutil.get_local_network).

The main network is derived from the host at every call (the interface chosen in iface, its address and mask): it is never written to disk and
nobody can change it. The networks written by the person come from storage/network_store.py (networks.json) and follow it; with no file the
world is the main network alone, and allowed() gives exactly what netutil.filter_local_ips allows (tests/check_networks_registry.py)."""
import ipaddress

from .. import netutil
from ..applog import logger
from ..storage import network_store
from . import host_read, legacy
from .model import Network, Rejected
from .scope import Scope

MAIN_ID = "main"
_not_proposed: set = set()      # (proposal, main network) that did not fit, not tried again while the main network stays the same
ROUTE_FILE = "/proc/net/route"


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


def _routes_now() -> list | None:
    """The networks of the main interface as the kernel routes them now (None if the routes cannot be read)."""
    return host_read.read_on_link(main_interface(), ROUTE_FILE)


def _held(ip, nets: list) -> bool:
    try:
        address = ipaddress.IPv4Address(ip)
    except (ValueError, TypeError):
        return False
    return any(address in n for n in nets)


def arp_targets(ips, cidr: str) -> list:
    """The addresses that may be asked by ARP, in the order given: those on the link of the main interface as the kernel routes it now; if
    the routes cannot be read, those of the main network `cidr` (K10). Right after a change of network the old addresses are already out."""
    nets = _routes_now()
    if nets is None:
        return scope_of(cidr).arp_targets(ips)
    return [ip for ip in ips if _held(ip, nets)]


def on_link(ip) -> bool:
    """One address may be asked by ARP now (K14): as arp_targets, with the network last read (netutil.last_network) when the routes cannot be
    read; False while nothing is known."""
    nets = _routes_now()
    if nets is None:
        cidr = netutil.last_network
        return bool(cidr) and scope_of(cidr).arp_targets([ip]) == [ip]
    return _held(ip, nets)


def still_routed(cidr: str) -> bool:
    """The main network kept in memory is still a route of the main interface (True when the routes cannot be read: nothing to compare)."""
    nets = _routes_now()
    return nets is None or ipaddress.ip_network(cidr) in nets


def scope_of(cidr: str) -> Scope:
    """The networks when the main one is `cidr` (already read): the main one first, then the written ones that fit next to it."""
    main_net = main_network(cidr)
    return Scope((main_net, *network_store.load(main_net)))


async def current() -> Scope:
    """The networks, the main one first."""
    cidr, _ = await main()
    return scope_of(cidr)


async def allowed(ips: list) -> list:
    """The addresses of `ips` that may be searched in depth, in the order given: those of a confirmed network whose devices may be touched
    fully (the main one, or a written network reached through the host's own interface with touch "full"). With the main network alone:
    exactly netutil.filter_local_ips, the warning in the log included, and the same ValueError on a value that is not an address (its callers
    check first; tests/check_networks_registry.py)."""
    scope = await current()
    for ip in ips:
        ipaddress.ip_address(ip)
    kept = scope.searchable(ips)
    rejected = [ip for ip in ips if ip not in set(kept)]
    if rejected:
        logger.warning("Scansione rifiutata, IP fuori dalla rete locale %s: %s", scope.networks[0].cidr, ", ".join(rejected))
    return kept


def _off_limits(ip, scope: Scope) -> bool:
    network = scope.held_by(ip)
    if network is not None:
        return network.state == "paused"
    return not legacy.admissible(ip)


def holds(network: Network, ip) -> bool:
    """The address is in the network (and not in one of its excluded ranges); False for a value that is not an IPv4 address."""
    try:
        return network.holds(ipaddress.IPv4Address(ip))
    except (ValueError, TypeError):
        return False


def mark_off_limits(devices: list) -> list:
    """The cards of one cycle, marked (never saved): touch_policy.OFF_LIMITS for those that may not be touched, an address in a paused network,
    or outside every network and not admissible (public, loopback, a container's: K8, K9b); touch_policy.NET_TOUCH with the most a confirmed
    written network allows ("presence": the ping adapter only, K1). Nothing is marked while the main network has not been read yet. A proposed
    network is touched as before (the grace period, K12)."""
    cidr = netutil.last_network
    if not cidr:
        return devices
    scope = scope_of(cidr)
    return [_marked(d, scope) for d in devices]


def _marked(device: dict, scope: Scope) -> dict:
    if _off_limits(device.get("ip"), scope):
        return {**device, "off_limits": True}
    network = scope.network_of(device.get("ip"))          # confirmed only: a proposed network is touched as before (K12)
    if network is not None and network.id != MAIN_ID and network.touch != "full":
        return {**device, "net_touch": network.touch}
    return device


def may_add(ip) -> bool:
    """A card with this address may be added (K9a): not in a paused network, and inside a network or admissible. True while the main network
    has not been read yet (the add itself reads nothing)."""
    cidr = netutil.last_network
    return not cidr or not _off_limits(ip, scope_of(cidr))


def propose(ips) -> list:
    """Store a proposed network for every /24 of admissible addresses outside every network (K12); the networks stored. A proposal that does not
    fit (overlap with the main network, too many networks) is not stored: its cards stay in no network and are touched as before."""
    cidr = netutil.last_network
    if not cidr:
        return []
    main_net = main_network(cidr)
    stored = []
    for candidate in legacy.proposals(ips, scope_of(cidr)):
        if (candidate["cidr"], cidr) in _not_proposed:
            continue
        try:
            stored.append(network_store.add(candidate, main_net))
        except Rejected as exc:
            _not_proposed.add((candidate["cidr"], cidr))          # said once in the log, not at every cycle
            logger.info("Rete %s non proposta: %s", candidate["cidr"], exc.code)
    if stored:
        logger.info("Reti proposte per le schede fuori dalla rete principale: %s", ", ".join(str(n.cidr) for n in stored))
    return stored

