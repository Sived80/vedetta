"""A network Vedetta may look at, and the check of one written by the person: validate() gives a Network or refuses it with a code (Rejected), and never fixes a value silently.

Pure: no disk, no clock, no network. Not used by the app yet (the work on more networks adds its callers one at a time).
The main network is not checked here: it is what the host says (netutil.get_local_network) and it is never written by anybody.

The limits below are a first proposal, to be confirmed with the preview of the panel before anybody can write a network:
at most MAX_NETWORKS networks (the main one counted), a network reached through the host's own interface at most a /16, one behind a router at most a /22, one seen only
through a controller, mDNS or SNMP at most a /24, none narrower than a /30. Networks may not overlap (decision D4 of 05/11): an address belongs to one network only."""
import ipaddress
from dataclasses import dataclass

PRIVATE = tuple(ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
CONTAINER = tuple(ipaddress.ip_network(n) for n in ("172.30.32.0/23", "172.17.0.0/16"))     # the network of the Supervisor and the default Docker bridge
MAX_NETWORKS = 8
WIDEST = {"direct": 16, "routed": 22}
WIDEST_OTHER = 24
NARROWEST = 30
MAX_EXCLUDE = 32
VIA = ("direct", "routed", "controller", "mdns", "snmp")      # how the network is seen: the host's own interface, through the router, or only told by another device
TOUCH = ("presence", "ports", "full")                         # the most a device of that network may be touched: answer or not, its ports, the whole search
STATES = ("proposed", "confirmed", "paused")
CODES = ("E_SHAPE", "E_CIDR", "E_NOT_IPV4", "E_BAD_VIA", "E_BAD_TOUCH", "E_BAD_STATE", "E_BAD_ID", "E_PUBLIC", "E_CONTAINER_NET", "E_TOO_WIDE", "E_TOO_NARROW",
         "E_TOUCH_NEEDS_DIRECT", "E_TOO_MANY", "E_DUP_ID", "E_OVERLAP", "E_BAD_EXCLUDE")


class Rejected(ValueError):
    """A network that cannot be accepted; `code` (one of CODES) says why, and is what the page translates."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Network:
    id: str
    cidr: ipaddress.IPv4Network
    via: frozenset
    touch: str
    state: str
    exclude: tuple = ()           # ranges of addresses left out, as (first, last) integers

    def holds(self, address: ipaddress.IPv4Address) -> bool:
        """The address is in the network and not in one of its excluded ranges."""
        return address in self.cidr and not any(lo <= int(address) <= hi for lo, hi in self.exclude)


def _cidr(text) -> ipaddress.IPv4Network:
    """The network written exactly ("192.168.60.0/24"): host bits set, spaces, or anything after it are refused, never corrected."""
    if not isinstance(text, str) or len(text) > 18 or not text.isascii():
        raise Rejected("E_CIDR")
    try:
        net = ipaddress.ip_network(text, strict=True)
    except ValueError:
        raise Rejected("E_CIDR") from None
    if net.version != 4:
        raise Rejected("E_NOT_IPV4")
    if str(net) != text:          # "10.0.0.0/08" is read as /8: a text that is not written the one way is refused, not rewritten
        raise Rejected("E_CIDR")
    return net


def _exclude(items, net: ipaddress.IPv4Network) -> tuple:
    """Addresses or "first-last" ranges inside the network."""
    if not isinstance(items, (list, tuple)) or len(items) > MAX_EXCLUDE:
        raise Rejected("E_BAD_EXCLUDE")
    return tuple(_range(item, net) for item in items)


def _range(item, net: ipaddress.IPv4Network) -> tuple[int, int]:
    """One excluded address ("192.168.60.7") or range ("192.168.60.200-192.168.60.220"), as (first, last) integers, both inside the network."""
    if not isinstance(item, str):
        raise Rejected("E_BAD_EXCLUDE")
    first, _, last = item.partition("-")
    try:
        lo, hi = ipaddress.ip_address(first.strip()), ipaddress.ip_address((last or first).strip())
    except ValueError:
        raise Rejected("E_BAD_EXCLUDE") from None
    if lo.version != 4 or hi.version != 4 or hi < lo or lo not in net or hi not in net:
        raise Rejected("E_BAD_EXCLUDE")
    return int(lo), int(hi)


def _id(value) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 16 or not value.isascii() or not value.replace("-", "").replace("_", "").isalnum():
        raise Rejected("E_BAD_ID")
    return value


def _via(value) -> frozenset:
    if not isinstance(value, (list, tuple, set, frozenset)) or not value or any(v not in VIA for v in value):
        raise Rejected("E_BAD_VIA")
    return frozenset(value)


def _choice(value, allowed: tuple, code: str) -> str:
    if value not in allowed:
        raise Rejected(code)
    return value


def _widest(via: frozenset) -> int:
    """The shortest prefix allowed: a network the host reaches itself may be wide, one seen through others less."""
    if "direct" in via:
        return WIDEST["direct"]
    return WIDEST["routed"] if "routed" in via else WIDEST_OTHER


def _check_place(net: ipaddress.IPv4Network, via: frozenset, touch: str) -> None:
    """Where the network may be: a private range, not the containers', not too wide or narrow; a whole search only on a network the host reaches itself."""
    if not any(net.subnet_of(p) for p in PRIVATE):
        raise Rejected("E_PUBLIC")
    if any(net.overlaps(c) for c in CONTAINER):
        raise Rejected("E_CONTAINER_NET")
    if net.prefixlen < _widest(via):
        raise Rejected("E_TOO_WIDE")
    if net.prefixlen > NARROWEST:
        raise Rejected("E_TOO_NARROW")
    if touch == "full" and "direct" not in via:
        raise Rejected("E_TOUCH_NEEDS_DIRECT")


def _check_others(nid: str, net: ipaddress.IPv4Network, existing) -> None:
    if len(existing) >= MAX_NETWORKS:
        raise Rejected("E_TOO_MANY")
    for other in existing:
        if other.id == nid:
            raise Rejected("E_DUP_ID")
        if other.cidr.overlaps(net):
            raise Rejected("E_OVERLAP")


def validate(candidate, existing) -> Network:
    """The Network a person wrote, checked against the networks that exist (the main one included); Rejected with a code otherwise."""
    if not isinstance(candidate, dict):
        raise Rejected("E_SHAPE")
    net = _cidr(candidate.get("cidr"))
    via = _via(candidate.get("via"))
    touch = _choice(candidate.get("touch", "presence"), TOUCH, "E_BAD_TOUCH")
    state = _choice(candidate.get("state", "proposed"), STATES, "E_BAD_STATE")
    nid = _id(candidate.get("id"))
    _check_place(net, via, touch)
    _check_others(nid, net, list(existing))
    return Network(nid, net, via, touch, state, _exclude(candidate.get("exclude", []), net))
