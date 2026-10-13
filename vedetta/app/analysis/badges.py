"""The badges of a card's icon. One class (Kind) per kind of badge, one function that chooses: at most one badge per corner and two in all, the strongest of each corner; the others are
told by `hidden` for the detail of the card. Corners: top_right = the state of the device, bottom_right = what is new or still settling. Pure; no colours here (the UI adds them for both
themes, and always a text or a shape beside the colour)."""
from typing import NamedTuple

TOP_RIGHT, BOTTOM_RIGHT = "top_right", "bottom_right"


class Kind(NamedTuple):
    id: str
    corner: str
    priority: int   # lower wins inside a corner


class Badge(NamedTuple):
    id: str
    corner: str
    text: str | None   # a short text, or None when the UI takes it from the language files by the id


KINDS = (Kind("no_touch", TOP_RIGHT, 10), Kind("fragile", TOP_RIGHT, 20), Kind("analysing", TOP_RIGHT, 30), Kind("unresolved", TOP_RIGHT, 30),
         Kind("new", BOTTOM_RIGHT, 10), Kind("settling", BOTTOM_RIGHT, 20), Kind("twin", BOTTOM_RIGHT, 30))
_CORNER_ORDER = (TOP_RIGHT, BOTTOM_RIGHT)


def _on(kind: Kind, flags: dict) -> bool:
    return bool(flags.get(kind.id))


def _badge(kind: Kind, flags: dict) -> Badge:
    return Badge(kind.id, kind.corner, str(flags[kind.id]) if kind.id == "twin" else None)


def _ranked(flags: dict) -> list[Kind]:
    """The kinds that are on, corner by corner (top first), the strongest first inside each corner."""
    on = [k for k in KINDS if _on(k, flags)]
    return sorted(on, key=lambda k: (_CORNER_ORDER.index(k.corner), k.priority))


def choose(flags: dict) -> list[Badge]:
    """The badges to show: the strongest of each corner."""
    seen, chosen = set(), []
    for kind in _ranked(flags):
        if kind.corner not in seen:
            seen.add(kind.corner)
            chosen.append(_badge(kind, flags))
    return chosen


def hidden(flags: dict) -> list[Badge]:
    """The badges that are on but did not fit: the detail of the card tells them."""
    shown = {b.id for b in choose(flags)}
    return [_badge(k, flags) for k in sorted((k for k in KINDS if _on(k, flags)), key=lambda k: KINDS.index(k)) if k.id not in shown]
