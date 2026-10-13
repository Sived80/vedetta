"""Twin cards: cards that look the same (same name, brand and type), like five Shelly called by their model. Only they need a number to be told apart; the number is the card's own
progressive number (storage/devices_config.py), which works for phones too. Pure function."""
from collections import defaultdict


def _look(card: dict) -> tuple:
    return ((card.get("name") or "").strip().lower(), (card.get("brand") or "").lower(), card.get("type") or "")


def twin_numbers(cards: list[dict]) -> dict[str, int]:
    """{card id: number} of the numbered cards that have at least one twin."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for card in cards:
        groups[_look(card)].append(card)
    return {c["id"]: c["seq"] for group in groups.values() if len(group) > 1 for c in group if c.get("seq") is not None}
