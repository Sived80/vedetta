"""Measures on real exports what the network-health rules would see (app/health/): for each export, how many devices drop off the network, how regular the drops of a device are (cyclic restarts) and how many devices drop in the same minutes (a common cause).
It reads the presence history of each export and prints numbers, not names; the thresholds of the rules are chosen from these numbers. Read-only; exports stay in ~/.vedetta/exports.
    python tools/replay_health.py [export.zip ...]"""
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vedetta"))
sys.path.insert(0, str(ROOT / "tools"))
import replay_mac_sharing as sharing  # noqa: E402
from app.health import detectors, matrix, signals  # noqa: E402

EXPORTS = Path.home() / ".vedetta" / "exports"
BIN_S = 120          # drops that fall in the same bin count as simultaneous


def drops_of(events) -> dict[str, list[float]]:
    return signals.drops_by_device([(device, bool(online), ts) for device, _mac, online, ts in events])


def regularity(times: list[float]) -> tuple[float, float] | None:
    """(mean interval in seconds, coefficient of variation) of a device with at least 4 drops; None otherwise."""
    if len(times) < 4:
        return None
    gaps = [b - a for a, b in zip(times, times[1:])]
    mean = statistics.fmean(gaps)
    return (mean, statistics.pstdev(gaps) / mean) if mean > 0 else None


def busiest_bins(drops: dict[str, list[float]]) -> Counter:
    bins = defaultdict(set)
    for device, times in drops.items():
        for t in times:
            bins[int(t // BIN_S)].add(device)
    return Counter({b: len(devs) for b, devs in bins.items()})


def judge_hourly(events, drops) -> dict[str, dict]:
    """The rules of the matrix judged at the end of every hour of the export (from the second day on): in how many hours each would have fired, and for how many different subjects."""
    start, end = events[0][3] + 86400, events[-1][3]
    rows = [r for r in matrix.load() if r["family"] in ("periodic_dropout", "simultaneous_drop")]
    fired = {r["id"]: {"hours": 0, "subjects": set()} for r in rows}
    hour = start
    while hour <= end:
        known = {device for device, _mac, _online, ts in events if hour - 86400 <= ts <= hour}
        seen = {"now": hour, "drops": drops, "devices": len(known)}
        for row in rows:
            found = detectors.FAMILIES[row["family"]](seen, row["params"])
            fired[row["id"]]["hours"] += bool(found)
            fired[row["id"]]["subjects"].update(e.subject for e in found)
        hour += 3600
    return fired


def report(path: Path) -> None:
    events = sharing.load_events(path)
    if not events:
        print(f"== {path.name}: no presence history, skipped")
        return
    drops = drops_of(events)
    span_d = (events[-1][3] - events[0][3]) / 86400
    total = sum(len(t) for t in drops.values())
    print(f"== {path.name}: {len({e[0] for e in events})} devices, {span_d:.1f} days, {total} drops, {len(drops)} devices dropped at least once")
    reg = {d: r for d, t in drops.items() if (r := regularity(t))}
    cyc = sorted(((cv, mean, len(drops[d])) for d, (mean, cv) in reg.items()), key=lambda x: x[0])
    print(f"   devices with >= 4 drops: {len(reg)}; most regular (cv, mean interval min, drops):")
    for cv, mean, n in cyc[:5]:
        print(f"     cv={cv:.2f} every {mean / 60:.0f} min, {n} drops")
    bins = busiest_bins(drops)
    print("   most devices dropping in the same %d s: %s" % (BIN_S, [n for _b, n in bins.most_common(5)]))
    print("   bins with >= 3 devices: %d, >= 5: %d" % (sum(n >= 3 for n in bins.values()), sum(n >= 5 for n in bins.values())))
    if span_d >= 1:
        for rule, got in judge_hourly(events, drops).items():
            print("   rule %s would have fired in %d hours, for %d different subjects" % (rule, got["hours"], len(got["subjects"])))


if __name__ == "__main__":
    paths = [Path(a) for a in sys.argv[1:]] or sorted(EXPORTS.glob("*.zip"))
    for p in paths:
        report(p)
