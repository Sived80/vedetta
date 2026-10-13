"""The links «this card is behind that repeater» which the data already prove (topology, phase T0). A MAC lent to several cards at the same time marks a
repeater (storage/overlap.py): the card that owns the MAC is the repeater, every other card that used it is attached to it. Pure functions: no database,
no clock, no network. Other sources of links (access point tables, SNMP, LLDP) will add edges of their own with their own `source`."""
from typing import Iterable, NamedTuple

from ..storage import overlap

SOURCE_LENT_MAC = "lent_mac"
SOURCE_HA_VIA = "ha_via_device"      # Home Assistant: the device says it is connected through another one (declared, not observed)
DECLARED_SOURCES = frozenset({SOURCE_HA_VIA})
MEDIUM_AFTER_S, HIGH_AFTER_S = 3600.0, 24 * 3600.0   # a link seen for less than an hour is weak, for a day or more it is solid


class Edge(NamedTuple):
    client: str     # card id
    parent: str     # card id of the repeater, or "mac:<mac>" when no card owns the lent MAC
    source: str
    seen_s: float   # seconds the client was seen online behind the parent


def lent_mac_edges(events: Iterable[tuple], candidates: dict[str, list[str]], horizon: float) -> list[Edge]:
    """Edges from (card, mac, online, ts) events. `candidates` maps a MAC to the cards that show it as their MAC now: the repeater is the one that was
    online with it the longest (it always answers with its own address, its clients come and go); with no candidate the parent is "mac:<mac>"."""
    found = []
    for mac, cards in overlap.sessions_by_mac(events, horizon).items():
        if not overlap.is_shared(cards):
            continue
        seen = {card: sum(end - start for start, end in spans) for card, spans in cards.items()}
        parent = max(candidates.get(mac) or [], key=lambda card: seen.get(card, 0.0), default=None) or "mac:" + mac
        found += [Edge(card, parent, SOURCE_LENT_MAC, secs) for card, secs in seen.items() if card != parent]
    return found


def confidence(edge: Edge) -> str:
    """low / medium / high: a declared link is high by itself, an observed one by how long it was observed."""
    if edge.source in DECLARED_SOURCES or edge.seen_s >= HIGH_AFTER_S:
        return "high"
    return "medium" if edge.seen_s >= MEDIUM_AFTER_S else "low"


def clients_placed(cards: list[str], edges: list[Edge]) -> float:
    """The share of cards that are the CLIENT of at least one link (graph.coverage also counts the parents: a repeater has a place because it has clients)."""
    placed = {e.client for e in edges}
    return sum(1 for c in cards if c in placed) / len(cards) if cards else 0.0
