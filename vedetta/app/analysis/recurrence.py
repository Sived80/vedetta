# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""How a device comes and goes over the last 30 days: seen once, occasional, recurring or stable. Pure: it is handed the online
segments of the device (history.presence_segments, the holes of Vedetta off already cut out), the time zone and "now".

  - a DAY is active when the device was online for some time of it (local day of Home Assistant);
  - the class is worked out on the history of THIS device: min(30 days, days since it was first seen), so a device that appeared
    3 days ago and was there every day is "stable", not "occasional" as against a month it was not there for;
  - with less than MIN_DAYS days of history the class is "observing": too early to say;
  - classes: one active day = "once"; active/history under 8/30 = "occasional"; under 21/30 = "recurring"; else "stable".
The strip of the 30 days (oldest first, the last one is today) is always read from the day of "now", never from a stored anchor."""
from datetime import datetime, timedelta, tzinfo

WINDOW_DAYS = 30
MIN_DAYS = 7
OCCASIONAL, STABLE = 8 / 30, 21 / 30
ONCE, OCCASIONAL_K, RECURRING, STABLE_K, OBSERVING = "once", "occasional", "recurring", "stable", "observing"


def day_of(ts: float, tz: tzinfo) -> int:
    return datetime.fromtimestamp(ts, tz).date().toordinal()


def active_days(segments: list[dict], tz: tzinfo) -> set[int]:
    """The local days (ordinals) touched by an online segment."""
    days: set[int] = set()
    for seg in segments:
        if not seg.get("online") or seg["to"] <= seg["from"]:
            continue
        first, last = day_of(seg["from"], tz), day_of(seg["to"] - 1e-6, tz)
        days.update(range(first, last + 1))
    return days


def classify(active: int, history_days: int) -> str:
    if history_days < MIN_DAYS:
        return OBSERVING
    if active <= 1:
        return ONCE
    ratio = active / history_days
    if ratio < OCCASIONAL:
        return OCCASIONAL_K
    if ratio < STABLE:
        return RECURRING
    return STABLE_K


def recurrence(segments: list[dict], first_seen: float | None, now: float, tz: tzinfo) -> dict:
    """{"class", "active_days", "history_days", "strip"}: strip = 30 booleans, oldest first, the last one today."""
    today = day_of(now, tz)
    window = range(today - WINDOW_DAYS + 1, today + 1)
    days = active_days(segments, tz) & set(window)
    history = WINDOW_DAYS if first_seen is None else max(1, min(WINDOW_DAYS, today - day_of(first_seen, tz) + 1))
    return {"class": classify(len(days), history), "active_days": len(days), "history_days": history,
            "strip": [d in days for d in window]}


def window_start(now: float, tz: tzinfo) -> float:
    """The start (local midnight) of the first day of the window: where to ask the segments from."""
    start = datetime.fromtimestamp(now, tz).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=WINDOW_DAYS - 1)
    return start.timestamp()
