"""Topology, phase T1 (read-only): the links of every source put together. One best link per (client, parent) with all the sources that told it; a client with two different parents of
similar strength is a conflict (a link to put under analysis); the cards with no known place are unknown and are never drawn as certain. Pure."""
from typing import Iterable, NamedTuple

from . import edges as edges_module

_RANK = {"low": 0, "medium": 1, "high": 2}


class Link(NamedTuple):
    client: str
    parent: str
    sources: list
    confidence: str


class Graph(NamedTuple):
    links: dict       # (client, parent) -> Link
    unknown: list     # cards with no known place, in the order they were given
    conflicts: list   # (client, [parents]) with parents of similar strength


def _stronger(first: str, second: str) -> str:
    return first if _RANK[first] >= _RANK[second] else second


def _merge(edge_lists: Iterable[list]) -> dict:
    links: dict = {}
    for edge in (e for lst in edge_lists for e in lst):
        key = (edge.client, edge.parent)
        level = edges_module.confidence(edge)
        old = links.get(key)
        links[key] = Link(edge.client, edge.parent, [edge.source], level) if old is None else Link(
            edge.client, edge.parent, old.sources + [s for s in [edge.source] if s not in old.sources], _stronger(old.confidence, level))
    return links


def _conflicts(links: dict) -> list:
    """Clients with several parents of the same (strongest) confidence."""
    by_client: dict = {}
    for link in links.values():
        by_client.setdefault(link.client, []).append(link)
    found = []
    for client, group in by_client.items():
        best = max(_RANK[link.confidence] for link in group)
        top = sorted(link.parent for link in group if _RANK[link.confidence] == best)
        if len(top) > 1:
            found.append((client, top))
    return found


def build(cards: list[str], *edge_lists: list) -> Graph:
    links = _merge(edge_lists)
    placed = {link.client for link in links.values()} | {link.parent for link in links.values()}
    return Graph(links, [c for c in cards if c not in placed], _conflicts(links))


def coverage(graph: Graph, cards: list[str]) -> float:
    """The share of the cards that have a place: a client with a link, or a parent that has clients."""
    placed = {link.client for link in graph.links.values()} | {link.parent for link in graph.links.values()}
    return sum(1 for c in cards if c in placed) / len(cards) if cards else 0.0
