"""Runs scenarios on the virtual LAN with the Vedetta found in a folder (the working tree, or another version checked out beside it to compare). Linux and root only:

    python3 tools/lansim/run_scenarios.py --code-dir vedetta [--scenario S5] [--label new]
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from tools.lansim.scenarios import SCENARIOS  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code-dir", default="vedetta", help="the folder that holds app/")
    parser.add_argument("--scenario", action="append", help="S1, S4, S5, S10, S10D (dense), S11, S12 (default: all)")
    parser.add_argument("--label", default="")
    args = parser.parse_args()
    code_dir = os.path.abspath(args.code_dir)
    for key in args.scenario or sorted(SCENARIOS):
        print("=== %s %s" % (key, args.label), flush=True)
        print(json.dumps(SCENARIOS[key](code_dir), indent=1, default=str), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
