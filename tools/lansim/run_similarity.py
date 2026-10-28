"""Builds the virtual LAN, lets the extender (or two of them, with the router's own Wi-Fi in the middle) hold and release three phones following a schedule, looks at the network cycle
after cycle with arp-scan and says whether what is seen resembles the real network (tools/lansim/metrics.py). Linux and root only:

    python3 tools/lansim/run_similarity.py [--cycles 300] [--seed 1] [--extenders 2]
"""
import argparse
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from tools.lansim import metrics, phases  # noqa: E402
from tools.lansim.lan import EXTENDER2_MAC, EXTENDER_MAC, Lan  # noqa: E402

CLIENTS = (("c1", "c6:00:00:00:00:21", 20), ("c2", "9a:00:00:00:00:22", 21), ("c3", "5a:00:00:00:00:23", 22))
EXTENDER_NAMES = ("ext", "ext2")


def _schedule(extenders: int, seed: int, cycles: int) -> list:
    """The holder of one phone in every cycle: None or the name of an extender."""
    rng = random.Random(seed)
    if extenders == 1:
        return ["ext" if held else None for held in phases.claim_schedule(rng, cycles)]
    return phases.roam_schedule(rng, cycles, EXTENDER_NAMES[:extenders])


def run(cycles: int, seed: int, extenders: int = 1) -> dict:
    """The summary of the measures for a simulated network of `cycles` cycles."""
    observations: list[metrics.Observation] = []
    with Lan(extenders) as lan:
        holder = {}
        schedules = {}
        for i, (name, mac, number) in enumerate(CLIENTS):
            address = lan.add_client(name, mac, number)
            schedules[name] = (address, _schedule(extenders, seed * 100 + i, cycles))
            holder[name] = None
        for cycle in range(cycles):
            for name, (address, schedule) in schedules.items():
                if schedule[cycle] != holder[name]:
                    holder[name] = schedule[cycle]
                    lan.hold(name, address, holder[name])
            seen = lan.arp_scan(CLIENTS[0][2], CLIENTS[-1][2])
            observations.extend(metrics.Observation(cycle, ip, mac) for ip, mac in seen.items())
    return metrics.summarize(observations, (EXTENDER_MAC, EXTENDER2_MAC)[:extenders] if extenders > 1 else EXTENDER_MAC)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=300)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--extenders", type=int, default=1, choices=(1, 2))
    args = parser.parse_args()
    summary = run(args.cycles, args.seed, args.extenders)
    print("%d changes in %d cycles, %d direct hand-offs between the extenders" % (summary["flips"], args.cycles, summary["handoffs"]))
    thresholds = {**metrics.THRESHOLDS, **(metrics.TWO_EXTENDERS if args.extenders == 2 else {})}
    rows = metrics.compare(summary, thresholds)
    for row in rows:
        v = row["value"]
        print("%-24s %-8s accepted %s..%s  %s" % (row["name"], "-" if v is None else ("%.2f" % v if isinstance(v, float) else v), row["low"], row["high"], "ok" if row["ok"] else "NO"))
    return 0 if all(r["ok"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
