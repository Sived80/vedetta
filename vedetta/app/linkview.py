"""The card -> MAC links as the cycle reads them (1.0 step P5): which stored link may be trusted now. cardlink_cycle fills it after every judgement
of the links (and once at start, from the last run) with the rows of History.card_links, its one reader; this module keeps that answer in memory,
so the probes of a cycle ask it at no cost. A link of card C to MAC M is used now when
  U1 the row is "linked" (a held one is not);
  U2 its seq is the card's (a card removed and added again with the same id inherits nothing);
  U3 its network is the card's network now (the caller works it out as the judgement does: routed cards, paused networks, a moved main network);
  U4 it has been stable for STABLE_S, two judgements (decision A of 12/11: a repeater linked to its own MAC just before it starts lending it);
  U5 a judgement of this run came at least JUDGE_S after it was made or changed (it was looked at again; after a restart the first one is enough);
  U6 the verdict of this cycle does not call M lent, virtual, on two addresses at once or in a conflict (the verdict is judged at every cycle,
     the links every JUDGE_S: this closes the gap between two judgements).
Nothing here writes a link: the release of a link (two cards of one phone merged) and the relink of the gesture "this is a new device" are
requests the one writer (cardlink_cycle -> History.store_card_links) takes at its next judgement. Imports macverdict only (pure)."""
from . import macverdict

JUDGE_S = 300.0                 # one judgement of the links every arpview.FULL_SWEEP_S (cardlink_cycle)
STABLE_S = 2 * JUDGE_S          # decision A of 12/11: a link is used once it has been stable for two judgements (about 10 minutes)
HOLD_KINDS = frozenset({"lender", "virtual", "multi_address", "conflict"})     # the kinds that hold a link (cardlink.HOLD_KINDS)
REASONS = ("none", "held", "seq", "network", "young", "unjudged", "kind", "released")   # why a link is not used now (the export counts them)

_rows: dict[str, dict] = {}
_judged: float | None = None            # when the last judgement of this run was made (None: none yet)
_released: set[str] = set()             # cards whose link is not used any more, until the writer took the request
_requests: dict[str, tuple] = {}        # device id -> ("release", None) or ("relink", MAC): asked of the one writer
_offers: dict[str, str] = {}            # device id -> the one other MAC that answers its address (the gesture "this is a new device")


def load(rows: dict[str, dict]) -> None:
    """At start: the rows stored by the last run; no judgement of this run has looked at them yet (U5)."""
    global _rows
    _rows = dict(rows or {})


def refresh(rows: dict[str, dict], judged_at: float, offers: dict[str, str] | None = None, done=()) -> None:
    """The rows just stored by a judgement made at `judged_at` replace the last ones in one step, with the offers of the gesture; `done`: the
    cards whose request the writer took (their request and release are forgotten)."""
    global _rows, _judged, _offers
    _rows, _judged, _offers = dict(rows or {}), judged_at, dict(offers or {})
    for device_id in done:
        _requests.pop(device_id, None)
        _released.discard(device_id)


def check(device_id: str, seq, network: str | None, now: float) -> tuple[str | None, str]:
    """(M, "used") when the link of the card may be used now, else (None, the reason: one of REASONS)."""
    r = _rows.get(device_id)
    reason = "none" if r is None else "released" if device_id in _released else _reason(r, seq, network, now)
    return (r["mac"], "used") if reason is None else (None, reason)


def _reason(r: dict, seq, network: str | None, now: float) -> str | None:
    if r["state"] != "linked":
        return "held"
    if r["seq"] != seq:
        return "seq"
    if network is None or r["network"] != network:
        return "network"
    if now - r["changed"] < STABLE_S:
        return "young"
    if _judged is None or _judged < r["changed"] + JUDGE_S:
        return "unjudged"
    return "kind" if macverdict.kind(r["mac"]) in HOLD_KINDS else None


def row(device_id: str) -> dict | None:
    """The stored row of the card's link (None without one)."""
    return _rows.get(device_id)


def release(device_id: str) -> None:
    """The link of the card is not used from now, and the writer deletes it at its next judgement (two cards of one phone were merged)."""
    _released.add(device_id)
    _requests[device_id] = ("release", None)


def relink(device_id: str, mac: str) -> None:
    """The gesture "this is a new device": the link of the card passes to `mac` at the next judgement (source "user"); the old one is not used
    meanwhile."""
    _released.add(device_id)
    _requests[device_id] = ("relink", mac)


def requests() -> dict[str, tuple]:
    """The requests waiting for the writer (a copy): device id -> (kind, MAC)."""
    return dict(_requests)


def offer(device_id: str) -> str | None:
    """The MAC the gesture "this is a new device" would link the card to, when the last judgement offered one."""
    return _offers.get(device_id)
