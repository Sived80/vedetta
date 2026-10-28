"""Builds the virtual LAN, lets the extender hold and release three phones following a schedule, looks at the network cycle after cycle with arp-scan and says
whether what is seen resembles the real network (tools/lansim/metrics.py). Linux and root only:

    python3 tools/lansim/run_similarity.py [--cycles 300] [--seed 1]
"""
import argparse
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from tools.lansim import metrics, phases  # noqa: E402
from tools.lansim.lan import EXTENDER_MAC, Lan  # noqa: E402

CLIENTS = (("c1", "c6:00:00:00:00:21", 20), ("c2", "9a:00:00:00:00:22", 21), ("c3", "5a:00:00:00:00:23", 22))


def run(cycles: int, seed: int) -> dict:
    """The summary of the measures for a simulated network of `cycles` cycles."""
    observations: list[metrics.Observation] = []
    with Lan() as lan:
        held_now = {}
        schedules = {}
        for i, (name, mac, number) in enumerate(CLIENTS):
            address = lan.add_client(name, mac, number)
            schedules[name] = (address, phases.claim_schedule(random.Random(seed * 100 + i), cycles))
            held_now[name] = False
        for cycle in range(cycles):
            for name, (address, schedule) in schedules.items():
                if schedule[cycle] != held_now[name]:
                    held_now[name] = schedule[cycle]
                    lan.hold(name, address, held_now[name])
            seen = lan.arp_scan(CLIENTS[0][2], CLIENTS[-1][2])
            observations.extend(metrics.Observation(cycle, ip, mac) for ip, mac in seen.items())
    return metrics.summarize(observations, EXTENDER_MAC)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=300)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    summary = run(args.cycles, args.seed)
    print("%d changes in %d cycles" % (summary["flips"], args.cycles))
    rows = metrics.compare(summary)
    for row in rows:
        v = row["value"]
        print("%-24s %-8s accepted %s..%s  %s" % (row["name"], "-" if v is None else ("%.2f" % v if isinstance(v, float) else v), row["low"], row["high"], "ok" if row["ok"] else "NO"))
    return 0 if all(r["ok"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
