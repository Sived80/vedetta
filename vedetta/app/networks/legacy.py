"""The cards that are already outside the main network (added by hand, or left from the network of before), and the addresses no card may have (K12).

Pure: it is handed the addresses and the networks. Two answers:
- admissible(ip): a private IPv4 address outside the containers' networks. Any other address (public, loopback, link-local, a container's) is never
  touched: a card with it is kept, shown, and not probed (K8, K9);
- proposals(ips, scope): the cards in no network, grouped by /24, as networks "proposed" behind the router. A proposed network is probed AS
  BEFORE (the grace period): nothing that worked stops working at the update; the person confirms it, pauses it or removes its cards."""
import ipaddress

from .model import CONTAINER, PRIVATE
from .scope import Scope

PREFIX = 24


def _address(ip) -> ipaddress.IPv4Address | None:
    try:
        return ipaddress.IPv4Address(ip)
    except (ValueError, TypeError):
        return None


def admissible(ip) -> bool:
    """An address outside every network that Vedetta may still touch: private IPv4, not in the containers' networks. The addresses of the
    main network are always touched, whatever they are (a provider's shared range included): the registry asks this only for the others."""
    address = _address(ip)
    return address is not None and any(address in p for p in PRIVATE) and not any(address in c for c in CONTAINER)


def _proposal_id(net: ipaddress.IPv4Network) -> str:
    return "p" + "-".join(str(net.network_address).split(".")[:3])          # "p192-168-60": at most 12 characters, as model._id wants


def proposals(ips, scope: Scope) -> list[dict]:
    """The networks to propose for the admissible addresses in no network of `scope` (any state counts: a paused network is a decision), one
    per /24, in the order of the first address of each; each a candidate for model.validate."""
    seen: dict = {}
    for ip in ips:
        if not admissible(ip) or _in_any(ip, scope):
            continue
        net = ipaddress.ip_network(f"{ip}/{PREFIX}", strict=False)
        seen.setdefault(net, None)
    return [{"id": _proposal_id(net), "cidr": str(net), "via": ["routed"], "touch": "presence", "state": "proposed"} for net in seen]


def _in_any(ip, scope: Scope) -> bool:
    address = _address(ip)
    return any(address in n.cidr for n in scope.networks)
