"""Time overlap of presence sessions, to tell a MAC lent to several cards (shared) from one phone that moved to a new address (not shared).
Pure functions: no database, no clock. A MAC is shared when two cards were online with it AT THE SAME TIME for longer than SAME_MOMENT_S (the failed
checks of tolerance and a lease handed over add a few minutes of overlap to a real move)."""
from collections import defaultdict
from itertools import combinations
from typing import Iterable

SAME_MOMENT_S = 30 * 60

Interval = tuple[float, float]


def overlap_seconds(first: list[Interval], second: list[Interval]) -> float:
    """Seconds in which two lists of intervals are both on."""
    return sum(max(0.0, min(a_end, b_end) - max(a_start, b_start)) for a_start, a_end in first for b_start, b_end in second)


def sessions(events: Iterable[tuple], horizon: float) -> list[tuple]:
    """(device, mac, online, ts) in time order -> (device, mac, start, end): an online event opens a session with its MAC, an offline one closes it,
    one still open ends at the horizon."""
    open_at: dict[str, tuple] = {}
    done = []
    for device, mac, online, ts in events:
        if online and device not in open_at:
            open_at[device] = (mac, ts)
        elif not online and device in open_at:
            opened_mac, start = open_at.pop(device)
            done.append((device, opened_mac, start, ts))
    done += [(device, mac, start, horizon) for device, (mac, start) in open_at.items()]
    return done


def sessions_by_mac(events: Iterable[tuple], horizon: float) -> dict[str, dict[str, list[Interval]]]:
    """mac -> card -> the intervals in which the card was online with that MAC."""
    by_mac: dict[str, dict[str, list[Interval]]] = defaultdict(lambda: defaultdict(list))
    for device, mac, start, end in sessions(events, horizon):
        if mac:
            by_mac[mac][device].append((start, end))
    return by_mac


def is_shared(cards: dict[str, list[Interval]], min_overlap_s: float = SAME_MOMENT_S) -> bool:
    """Two of these cards were online together for longer than min_overlap_s."""
    return any(overlap_seconds(a, b) > min_overlap_s for a, b in combinations(cards.values(), 2))


def shared_macs(events: Iterable[tuple], horizon: float, min_overlap_s: float = SAME_MOMENT_S) -> set[str]:
    """The MACs that two different cards used at the same time for longer than min_overlap_s."""
    return {mac for mac, cards in sessions_by_mac(events, horizon).items() if is_shared(cards, min_overlap_s)}
