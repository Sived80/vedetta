"""Topology, phase T0: the links the presence history of real exports already prove (a MAC lent to several cards = a repeater with its clients), with
the confidence of each and how many cards get a known place. Read-only; exports stay in ~/.vedetta/exports. Prints the type and the last part of the
address of each card, never a name.
    python tools/replay_topology.py [export.zip ...]"""
import json
import sys
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vedetta"))
sys.path.insert(0, str(ROOT / "tools"))
from app.topology import edges, graph  # noqa: E402
import replay_mac_sharing as sharing  # noqa: E402


def cards_of(path: Path) -> dict[str, dict]:
    with zipfile.ZipFile(path) as z:
        return {d["id"]: d for d in json.loads(z.read("state/devices_compact.json"))}


def label(card_id: str, cards: dict) -> str:
    card = cards.get(card_id)
    return f"{card.get('type') or '-'}@.{card['ip'].split('.')[-1]}" if card else card_id[:12]


def replay(path: Path) -> tuple[int, int, int]:
    cards = cards_of(path)
    events = sharing.load_events(path)
    owners: dict[str, list[str]] = {}
    for cid, c in cards.items():
        if c.get("mac"):
            owners.setdefault(c["mac"].lower(), []).append(cid)
    found = edges.lent_mac_edges(events, owners, max(e[3] for e in events)) if events else []
    by_parent: dict[str, list] = {}
    for e in found:
        by_parent.setdefault(e.parent, []).append(e)
    g = graph.build(list(cards), found)
    print(f"== {path.name}: {len(cards)} cards, {len(found)} links, places known {graph.coverage(g, list(cards)):.0%}, unknown {len(g.unknown)}, conflicts {len(g.conflicts)}")
    for parent, links in sorted(by_parent.items()):
        levels = Counter(edges.confidence(e) for e in links)
        print(f"   behind {label(parent, cards)}: " + ", ".join(f"{label(e.client, cards)} ({edges.confidence(e)}, {e.seen_s / 3600:.1f} h)" for e in sorted(links)))
        print(f"      confidence {dict(levels)}")
    return len(cards), len(found), len(by_parent)


def main(argv: list[str]) -> None:
    paths = [Path(a) for a in argv] or sorted(sharing.EXPORTS.glob("*.zip"))
    totals = [replay(p) for p in paths]
    print(f"\n{len(paths)} exports, {sum(t[1] for t in totals)} links, {sum(t[2] for t in totals)} repeaters found")


if __name__ == "__main__":
    main(sys.argv[1:])
