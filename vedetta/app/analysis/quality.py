"""The quality of a device's link, from what Vedetta already keeps: the response times (one average a minute, 7 days) and the presence
segments (the holes of Vedetta off already cut out). Pure.

  - typical time = the MEDIAN of the 7 days, and its spread = the MAD (median absolute deviation): robust, a few Wi-Fi spikes do not
    move them the way they move a mean and a standard deviation;
  - now: the robust z of the last value, 0.6745 x (x - median) / MAD; over 3.5 "anomalous", over 2.5 "high", else "normal"; with fewer
    than MIN_SAMPLES values, or no last value, "unknown"; with a MAD of 0 (a device that always answers in the same time) a last
    value above the median by more than 1 ms is "high";
  - trend: the median of the last 6 hours against the one of the 18 hours before, at least 3 values each; over +15 % "rising",
    under -15 % "falling", else "stable";
  - changes in 24 hours: how many times the device went from online to offline or back;
  - longest outage in 7 days: the longest offline segment (a segment still open counts up to now)."""
from statistics import median

MIN_SAMPLES = 10
Z_HIGH, Z_ANOMALOUS = 2.5, 3.5
TREND_PCT = 15.0
HOUR = 3600


def mad(values: list[float], centre: float) -> float:
    return median(abs(v - centre) for v in values)


def level(last: float | None, values: list[float]) -> tuple[str, float | None]:
    if last is None or len(values) < MIN_SAMPLES:
        return "unknown", None
    centre = median(values)
    spread = mad(values, centre)
    if spread == 0:
        return ("high" if last - centre > 1.0 else "normal"), None
    z = 0.6745 * (last - centre) / spread
    return ("anomalous" if z > Z_ANOMALOUS else "high" if z > Z_HIGH else "normal"), round(z, 1)


def trend(points: list[tuple[float, float]], now: float) -> tuple[str, float | None]:
    recent = [ms for ts, ms in points if ts >= now - 6 * HOUR]
    older = [ms for ts, ms in points if now - 24 * HOUR <= ts < now - 6 * HOUR]
    if len(recent) < 3 or len(older) < 3 or median(older) <= 0:
        return "unknown", None
    pct = (median(recent) - median(older)) / median(older) * 100
    return ("rising" if pct > TREND_PCT else "falling" if pct < -TREND_PCT else "stable"), round(pct)


def changes(segments: list[dict], since: float) -> int:
    """Online/offline changes after `since`: between two consecutive segments of different state (a hole of Vedetta off is no change)."""
    n = 0
    for a, b in zip(segments, segments[1:]):
        if b["from"] >= since and a["online"] != b["online"] and abs(a["to"] - b["from"]) < 1e-6:
            n += 1
    return n


def longest_outage(segments: list[dict]) -> float | None:
    off = [s["to"] - s["from"] for s in segments if not s["online"]]
    return round(max(off)) if off else None


def quality(points: list[tuple[float, float]], segments_7d: list[dict], now: float) -> dict:
    values = [ms for _, ms in points]
    last = points[-1][1] if points else None
    lv, z = level(last, values)
    tr, pct = trend(points, now)
    return {"samples": len(values), "median_ms": round(median(values), 1) if values else None,
            "mad_ms": round(mad(values, median(values)), 1) if values else None, "last_ms": last, "level": lv, "z": z,
            "trend": tr, "trend_pct": pct, "changes_24h": changes(segments_7d, now - 24 * HOUR), "longest_outage_s": longest_outage(segments_7d)}
