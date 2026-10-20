"""The detectors: one small pure function for each family of problem. A detector reads the signals and the parameters of its row and returns the evidence it finds (nothing if the signal is quiet or unreadable). Evidence holds counts and device ids, never addresses or names."""
import statistics
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Evidence:
    subject: str                       # whom it is about: a device id, "lan", "gateway", "internet" or "self"
    data: dict = field(default_factory=dict)


def conflict(signals: dict, params: dict) -> list[Evidence]:
    """An IP answered by more than one MAC (signals["conflicts"]: ip -> list of MACs)."""
    conflicts = signals.get("conflicts")
    if not isinstance(conflicts, dict) or not conflicts:
        return []
    return [Evidence("lan", {"ips": len(conflicts), "macs": sum(len(macs) for macs in conflicts.values())})]


def _recent(drops, now: float, window_s: float) -> dict[str, list[float]]:
    """The drops of each device inside the window that ends now; {} if the signal is not a dict of lists."""
    if not isinstance(drops, dict):
        return {}
    return {device: [t for t in times if now - window_s <= t <= now] for device, times in drops.items()}


def periodic_dropout(signals: dict, params: dict) -> list[Evidence]:
    """A device that drops again and again at almost the same interval (a restart that repeats): enough drops in the window, an interval between the two limits, and a small spread of the intervals (coefficient of variation)."""
    now = signals.get("now")
    if not isinstance(now, (int, float)):
        return []
    found = []
    for device, times in _recent(signals.get("drops"), now, params["window_s"]).items():
        if len(times) < params["min_drops"]:
            continue
        gaps = [b - a for a, b in zip(times, times[1:])]
        mean = statistics.fmean(gaps)
        cv = statistics.pstdev(gaps) / mean if mean > 0 else None
        if cv is not None and params["min_period_s"] <= mean <= params["max_period_s"] and cv <= params["max_cv"]:
            found.append(Evidence(device, {"drops": len(times), "period_s": round(mean), "cv": round(cv, 2)}))
    return found


def simultaneous_drop(signals: dict, params: dict) -> list[Evidence]:
    """Many devices that drop in the same short stretch of time (a common cause): at least min_devices, and at least min_fraction of the devices that are known, inside one bin of bin_s seconds, within the last window_s."""
    now, devices = signals.get("now"), signals.get("devices")
    if not isinstance(now, (int, float)) or not isinstance(devices, int) or devices < 1:
        return []
    bins: dict[int, set] = {}
    for device, times in _recent(signals.get("drops"), now, params["window_s"]).items():
        for t in times:
            bins.setdefault(int(t // params["bin_s"]), set()).add(device)
    group = max(bins.values(), key=len, default=set())
    if len(group) >= params["min_devices"] and len(group) >= params["min_fraction"] * devices:
        return [Evidence("lan", {"devices": len(group), "of": devices, "ids": sorted(group)})]
    return []


def _values(samples, after: float, until: float) -> list[float]:
    """The values of the samples (ts, ms) with after < ts <= until; a sample without a value is left out."""
    return [ms for ts, ms in samples if ms is not None and after < ts <= until]


def _stepped(recent: list[float], base: list[float], params: dict) -> tuple[float, float] | None:
    """(before, after) when the median of `recent` is above the median of `base` by more than k times its spread (MAD), by more than abs_min_ms and by at least `ratio` times; None otherwise."""
    after, before = statistics.median(recent), statistics.median(base)
    spread = 1.4826 * statistics.median(abs(x - before) for x in base)
    if after - before >= max(params["abs_min_ms"], params["k"] * spread) and after >= params["ratio"] * before:
        return before, after
    return None


def step_change(signals: dict, params: dict) -> list[Evidence]:
    """A step of a latency series (signals["latency"]: subject -> [(ts, ms)]): the median of the last recent_s seconds against the 6 hours (baseline_s) before them. There is a floor in milliseconds because a wired LAN answers in half a
    millisecond: a ratio alone would shout at a tenth of a millisecond. The median ignores a single spike. Too few samples in either window say nothing."""
    now, series = signals.get("now"), signals.get("latency")
    if not isinstance(now, (int, float)) or not isinstance(series, dict):
        return []
    found = []
    for subject, samples in series.items():
        if not isinstance(samples, (list, tuple)):
            continue
        recent = _values(samples, now - params["recent_s"], now)
        base = _values(samples, now - params["recent_s"] - params["baseline_s"], now - params["recent_s"])
        if len(recent) < params["min_recent"] or len(base) < params["min_baseline"]:
            continue
        step = _stepped(recent, base, params)
        if step:
            found.append(Evidence(subject, {"from_ms": round(step[0], 1), "to_ms": round(step[1], 1)}))
    return found


FAMILIES = {"conflict": conflict, "periodic_dropout": periodic_dropout, "simultaneous_drop": simultaneous_drop, "step_change": step_change}
