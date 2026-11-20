"""Twin cards: one machine with an address on two networks (the router of the house and its leg on a VLAN, Home Assistant with an address
on a VLAN) has two cards, one per address. The card on the main network is the main one; the other is its twin: it takes the main card's
name with the network after it ("Home Assistant (VLAN 20)"), and the page puts it next to the main one (decision B of 18/11; one card with
all the addresses is for after 1.0).

Pure: it is handed the cards, the addresses of the host Vedetta runs on, its own address, the MACs that are lent (a repeater answering for
its clients: the same MAC there says nothing) and the network of an address. Three ways to be a twin, the first that applies wins:
  - an address of the host itself on another network: the twin of the card at the host's own address (the host has no MAC in its own ARP table);
  - the same MAC as a card on another network (a MAC that is not lent): the twin of the card on the main network;
  - the same TLS certificate (`tls_fp`, its SHA-256 fingerprint from the deep search) as a card on another network: the twin of the card on the
    main network (1.0.1: a VLAN reached only through the router shows no MAC, but the router presents one certificate on every address). A
    certificate shared by two cards of one network says nothing (two devices of one maker with its default certificate): ignored."""
from collections.abc import Callable

from .formatters import MAX_NAME_LEN, truncate_name
from .storage.newdevices import normalize_mac

MAIN_NETWORK = "main"
SOURCE = "twin"          # the name_source of a twin's name: never replaced by an automatic name, released when the card stops being a twin


def find(cards: list[dict], host_ips: set, own_ip: str | None, lenders: frozenset, network_of: Callable) -> dict[str, str]:
    """{twin card id: main card id}."""
    out = _host_twins(cards, host_ips, own_ip, network_of)
    groups = [*_by_mac(cards, lenders).values(), *_by_cert(cards, network_of)]
    for group in groups:
        for twin, main in _group_twins(group, network_of).items():
            out.setdefault(twin, main)
    return out


def _group_twins(group: list[dict], network_of: Callable) -> dict[str, str]:
    """Cards of one machine (one MAC, one certificate): those on another network than the card on the main network are its twins (none without
    a card on the main network)."""
    main = next((c for c in group if _net_id(network_of(c["ip"])) == MAIN_NETWORK), None)
    if main is None:
        return {}
    return {c["id"]: main["id"] for c in group if c is not main and _net_id(network_of(c["ip"])) not in (None, MAIN_NETWORK)}


def _host_twins(cards: list[dict], host_ips: set, own_ip: str | None, network_of: Callable) -> dict[str, str]:
    main = next((c for c in cards if own_ip and c.get("ip") == own_ip), None)
    if main is None:
        return {}
    home = _net_id(network_of(own_ip))
    return {c["id"]: main["id"] for c in cards
            if c is not main and c.get("ip") in host_ips and _net_id(network_of(c["ip"])) not in (None, home)}


def _by_mac(cards: list[dict], lenders: frozenset) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for card in cards:
        mac = normalize_mac(card.get("mac"))
        if mac and mac not in lenders and card.get("ip"):
            groups.setdefault(mac, []).append(card)
    return {m: g for m, g in groups.items() if len(g) > 1}


def _by_cert(cards: list[dict], network_of: Callable) -> list[list[dict]]:
    """Cards with the same certificate fingerprint, on different networks (a fingerprint with two cards on one network is ignored)."""
    groups: dict[str, list[dict]] = {}
    for card in cards:
        fp = str(card.get("tls_fp") or "").lower()
        if fp and card.get("ip"):
            groups.setdefault(fp, []).append(card)
    return [g for g in groups.values() if len(g) > 1 and _one_per_network(g, network_of)]


def _one_per_network(group: list[dict], network_of: Callable) -> bool:
    nets = [n for n in (_net_id(network_of(c["ip"])) for c in group) if n is not None]
    return len(nets) == len(set(nets))


def _net_id(network) -> str | None:
    return getattr(network, "id", None)


def label(network) -> str | None:
    """How a twin's network is told after the name: the name the person gave it, else its VLAN number, else its address."""
    if network is None:
        return None
    if getattr(network, "name", None):
        return network.name
    if getattr(network, "vlan", None) is not None:
        return "VLAN %d" % network.vlan
    return str(network.cidr)


def name(main_name: str | None, network) -> str | None:
    """The twin's name: the main card's name and its network ("Gateway-1 (VLAN 20)"); None when either is missing. Never longer than a card
    name may be (MAX_NAME_LEN): the main name is shortened first, so the network stays readable (18/11 review: a longer one was cut by the
    probe and written again at every cycle)."""
    where = label(network)
    if not (main_name and where):
        return None
    suffix = " (%s)" % where
    room = MAX_NAME_LEN - len(suffix)
    head = main_name if len(main_name) <= room else main_name[:max(1, room - 1)].rstrip() + "…"
    return truncate_name(head + suffix)
