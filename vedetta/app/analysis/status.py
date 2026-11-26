"""Is a device identified, settling or under analysis? Phase 1: read-only, from the evidence card the app already builds (recognition/evidence.py); it sends nothing.
The shape of the rule comes from other fields (PRATICA_CORRETTA, part 2): two thresholds with a middle zone where the state is kept (Fellegi and Sunter's record linkage;
the hysteresis of flap detection), a grace period for a card that has just appeared (cold start of a new item), and a conflict between pieces of evidence that counts whatever the
age. The numbers are placeholders to be measured on the exports (tools/replay_analysis.py), not taken from a book."""
from typing import NamedTuple

IDENTIFIED, SETTLING, ANALYSING, UNRESOLVED = "identified", "settling", "analysing", "unresolved"
LOW, HIGH = 50, 60          # certainty (0-100): below LOW it enters analysis, at HIGH or more it leaves; in between it keeps its state
GRACE_S = 2 * 3600          # a card younger than this is only "settling" when its certainty is low (to be measured)
MAX_ANALYSIS_S = 7 * 86400  # a card that has been under analysis this long and still is stays "unresolved": nobody could tell what it is, so the person is asked to name it (working value, to be measured)
CLOSE_POINTS = 3            # the first and the second group closer than this compete


class Status(NamedTuple):
    state: str
    reasons: list


def assess(group: dict, *, age_s: float, previous: str | None = None, scores: dict | None = None, chosen: str | None = None, analysing_for_s: float | None = None) -> Status:
    """`group` is the "group" part of the evidence card; scores and chosen (the points per group and the group shown) are optional and tell an override. `analysing_for_s` is how long the card has been
    under analysis without a break: from MAX_ANALYSIS_S on, a card that is still under analysis is «unresolved» (the reason «expired» says why). Its evidence is judged exactly as before: if it improves, the card is identified and the clock stops."""
    result = _judge(group, age_s, previous, scores, chosen)
    if result.state == ANALYSING and analysing_for_s is not None and analysing_for_s >= MAX_ANALYSIS_S:
        return Status(UNRESOLVED, result.reasons + ["expired"])
    return result


def _judge(group: dict, age_s: float, previous: str | None, scores: dict | None, chosen: str | None) -> Status:
    if group.get("basis") == "manual":
        return Status(IDENTIFIED, [])
    low = _low_certainty(group.get("certainty", 100), previous)
    conflicts = [name for name, found in (("override", _override(scores, chosen)), ("close", _close(group, scores, chosen))) if found]
    # Low certainty is a matter for analysis only when there is something to test: a rival group, or no type at all. A single clue with no rival (a smart-home device known only by its
    # platform) is "thin": the type is not contradicted, it is just poorly supported; it is told, but it does not open an analysis.
    open_question = bool(group.get("rejected")) or group.get("value") in (None, "generic")
    reasons = (["low_certainty" if open_question else "thin"] if low else []) + conflicts
    if conflicts:
        return Status(ANALYSING, reasons)
    if low and open_question:
        return Status(SETTLING if age_s < GRACE_S else ANALYSING, reasons)
    return Status(IDENTIFIED, reasons)


def _low_certainty(certainty: float, previous: str | None) -> bool:
    """Below LOW; or, for a card that was under analysis (also an unresolved one), below HIGH (it must climb past the high threshold to leave)."""
    return certainty < (HIGH if previous in (ANALYSING, UNRESOLVED) else LOW)


def _override(scores: dict | None, chosen: str | None) -> bool:
    """The group shown is not the one with the most points (for example the mobile score won over the router points)."""
    if not scores or chosen in (None, "generic"):
        return False
    return chosen != max(scores, key=scores.get)


def _close(group: dict, scores: dict | None, chosen: str | None) -> bool:
    """Another group is as good as the chosen one: its points are within CLOSE_POINTS of the points that decided. The points of the chosen group are its real score when it is known (the card shows only
    its four strongest clues, so their sum can be too low); otherwise the sum of the clues."""
    top = scores[chosen] if scores and chosen in scores else sum(c.get("points", 0) for c in group.get("clues") or [])
    return top > 0 and any(r.get("points", 0) >= top - CLOSE_POINTS for r in group.get("rejected") or [])
