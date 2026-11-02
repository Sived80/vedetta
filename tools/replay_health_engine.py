"""Replays the history of real exports through the judge of the network health as it runs in the app (health/engine.py, one judgment every REFRESH_S seconds, with its opening and closing
cycles), for the rules that read the history: H05 (restarts that repeat), H06 (devices that drop together) and H07 (a step of the gateway latency). It says how often each rule would have raised
a finding, for how long and for which devices: on real networks every raise is either a real problem or a false alarm, and it is looked at one by one.
A fault can be added to the real history, half way through it, to see that the rule raises it and how soon:
    periodic:<period_s>:<count>   a made-up device that drops and comes back every period_s seconds, count times
    together:<n>                  n of the devices of the export drop in the same minute and come back five minutes later
    step:<ms>                     the latency of the gateway is ms higher from then on, for one hour (half way through the latency the export keeps)
Read-only; prints numbers and the ids of the cards (local data, never committed).
    python tools/replay_health_engine.py [--inject periodic:600:8] export.zip [...]"""
import argparse
import bisect
import json
import sys
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vedetta"))
sys.path.insert(0, str(ROOT / "tools"))
import replay_health  # noqa: E402
import replay_mac_sharing as sharing  # noqa: E402
from app.ha.health_view import LATENCY_WINDOW_S, REFRESH_S, SIGNAL_WINDOW_S  # noqa: E402
from app.health import engine, matrix, signals  # noqa: E402

FAMILIES = ("periodic_dropout", "simultaneous_drop", "step_change")
TARGET = {"periodic": "H05", "together": "H06", "step": "H07"}     # the rule each made-up fault is for


def inject(kind: str, events: list[tuple], latency: list[tuple], at: float, mobile: set = frozenset()) -> tuple[list[tuple], list[tuple], str | None]:
    """The history with one made-up fault from `at` on, and the subject the rule should name (None when it is the whole LAN)."""
    name, *args = kind.split(":")
    events, latency = list(events), list(latency)
    if name == "periodic":
        period, count = float(args[0]), int(args[1])
        events.append(("injected-device", None, 1, at - 3600))
        for i in range(count):
            t = at + i * period
            events += [("injected-device", None, 0, t), ("injected-device", None, 1, t + 60)]
        return sorted(events, key=lambda e: e[3]), latency, "injected-device"
    if name == "together":
        busy = [d for d, _n in Counter(e[0] for e in events if e[3] <= at and e[0] not in mobile).most_common(int(args[0]))]
        events += [e for d in busy for e in ((d, None, 0, at + 5), (d, None, 1, at + 300))]
        return sorted(events, key=lambda e: e[3]), latency, "lan"
    if name == "step":
        extra = float(args[0])
        return events, [(ts, ms + extra if ms is not None and at <= ts <= at + 3600 else ms) for ts, ms in latency], "gateway"
    raise SystemExit("unknown fault: " + kind)


def cards_of(path: Path) -> tuple[set, set]:
    """The ids of the cards of the export, and of the ones it marks as mobile: as in the app, only devices with a card are judged and the rules on drops leave the phones out."""
    with zipfile.ZipFile(path) as z:
        cards = json.loads(z.read("state/devices_compact.json")) if "state/devices_compact.json" in z.namelist() else []
    cards = cards["devices"] if isinstance(cards, dict) else cards
    return {c["id"] for c in cards}, {c["id"] for c in cards if c.get("is_mobile")}


def replay(events: list[tuple], latency: list[tuple], mobile: set = frozenset(), start: float | None = None, end: float | None = None) -> dict:
    """Every judgment from one day after the first event (or from `start`) to the last one (or `end`): the changes of each rule, the hours each finding stayed active and when it was first raised. The fixed devices on the network
    in the day are counted as the app does: an event in the day, or online at that moment (here: the last event before it says online)."""
    rows = [r for r in matrix.load() if r["family"] in FAMILIES]
    judge = engine.Engine(rows)
    drops = signals.drops_by_device([(d, bool(o), ts) for d, _m, o, ts in events])
    times = [e[3] for e in events]
    lat_ts = [ts for ts, _ms in latency]
    out = {r["id"]: {"changes": Counter(), "active_s": 0.0, "raised": []} for r in rows}
    now = events[0][3] + SIGNAL_WINDOW_S if start is None else start
    end = events[-1][3] if end is None else end
    online, done = {}, 0
    while now <= end:
        lo = bisect.bisect_left(times, now - SIGNAL_WINDOW_S)
        hi = bisect.bisect_right(times, now)
        for device, _mac, is_on, _ts in events[done:hi]:
            online[device] = bool(is_on)
        done = hi
        present = {e[0] for e in events[lo:hi]} | {d for d, is_on in online.items() if is_on}
        window = latency[bisect.bisect_left(lat_ts, now - LATENCY_WINDOW_S):bisect.bisect_right(lat_ts, now)]
        seen = {"now": now, "drops": drops, "mobile": mobile, "devices": len(present - mobile), "latency": {"gateway": window} if window else {}}
        for c in judge.judge(seen, now):
            out[c.finding.rule]["changes"][c.change] += 1
            if c.change == "raised":
                out[c.finding.rule]["raised"].append((now, c.finding.subject))
        for f in judge.findings():
            if f.state == "active":
                out[f.rule]["active_s"] += REFRESH_S
        now += REFRESH_S
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--inject", help="periodic:<period_s>:<count>, together:<n> or step:<ms>")
    parser.add_argument("exports", nargs="+")
    args = parser.parse_args()
    for path in map(Path, args.exports):
        ids, mobile = cards_of(path)
        events = [e for e in sharing.load_events(path) if e[0] in ids]
        if not events or events[-1][3] - events[0][3] < 2 * SIGNAL_WINDOW_S:
            print(f"== {path.name}: less than two days of history, skipped")
            continue
        latency = replay_health.gateway_latency(path)
        at, subject = (events[0][3] + events[-1][3]) / 2, None
        if args.inject and args.inject.startswith("step") and latency:
            at = latency[len(latency) // 2][0]          # the latency of an export covers its last days only, and may have gaps: the middle sample
        if args.inject:
            events, latency, subject = inject(args.inject, events, latency, at, mobile)
        days = (events[-1][3] - events[0][3]) / 86400
        print(f"== {path.name}: {days:.1f} days, {len({e[0] for e in events})} devices, gateway latency {'yes' if latency else 'no'}" + (f", fault {args.inject}" if args.inject else ""))
        for rule, got in replay(events, latency, mobile).items():
            subjects = Counter(s for _t, s in got["raised"])
            line = f"   {rule}: raised {got['changes']['raised']}, closed {got['changes']['closed']}, active {got['active_s'] / 3600:.1f} h, subjects {dict(subjects)}"
            if args.inject and rule == TARGET[args.inject.split(":")[0]]:
                hit = [t for t, s in got["raised"] if t >= at and s == subject]
                line += f" | fault: {'raised after %.0f min' % ((hit[0] - at) / 60) if hit else 'NOT raised'}"
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
