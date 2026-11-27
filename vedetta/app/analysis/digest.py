# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The summary of a window (the night, the last hours): what is NEW, what CAME BACK after a long absence, what went SILENT. Pure: it
is handed the cards (when each was first and last seen, online now or not, phone or tablet, whether Vedetta could watch it), the
returns after a long absence (history.returns_after) and the window.

Only the changes of THIS window, never the states: a device off for weeks is not said again every night, only the night it crosses
the line. And only where Vedetta could see: a card it does not watch (a paused network, a card that may not be touched) says nothing
by its silence. Phones and tablets come and go: they are never "silent". The first window of an installation claims no change
(there is nothing before it). The word "removed" is never used: "silent", "not seen".

  - new: first seen inside the window;
  - back: online again inside the window after at least `back_after_s` offline (a long absence, not a phone asleep);
  - silent: last seen at least `silent_after_s` before the end of the window, but less than that before its start: it crossed the
    line during the window;
  - counts: how many cards, how many online now."""

DEFAULT_SILENT_S = 24 * 3600
DEFAULT_BACK_S = 24 * 3600


def digest(cards: dict, returns: list[tuple[str, float, float]], start: float, end: float, *, installed_at: float | None,
           silent_after_s: float = DEFAULT_SILENT_S, back_after_s: float = DEFAULT_BACK_S) -> dict:
    if installed_at is None or installed_at >= start:
        return {"from": start, "to": end, "first_window": True, "new": [], "back": [], "silent": [], "cards": len(cards),
                "online": sum(1 for c in cards.values() if c.get("online"))}
    new = sorted((cid for cid, c in cards.items() if c.get("first_seen") is not None and start < c["first_seen"] <= end),
                 key=lambda cid: cards[cid]["first_seen"])
    back = [{"id": cid, "at": at, "away_s": round(off)} for cid, at, off in returns
            if cid in cards and off >= back_after_s and start < at <= end and cid not in new]
    silent = sorted((cid for cid, c in cards.items() if _went_silent(c, start, end, silent_after_s)),
                    key=lambda cid: cards[cid]["last_seen"])
    return {"from": start, "to": end, "first_window": False, "new": new, "back": back, "silent": silent, "cards": len(cards),
            "online": sum(1 for c in cards.values() if c.get("online"))}


def _went_silent(card: dict, start: float, end: float, after: float) -> bool:
    last = card.get("last_seen")
    if card.get("online") or last is None or card.get("is_mobile") or not card.get("watched", True):
        return False
    return end - last >= after > start - last
