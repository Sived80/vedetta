"""A campaign on the virtual LAN: every scenario run again and again, with other seeds where the scenario takes one, each run judged by what the scenario promises (pass, fail, a known
limit that is on the list, or a study that has no right answer). One line of JSON per run goes to the results file as soon as the run ends, so a campaign stopped half way keeps
what it did. Linux and root only, a few hours:

    python3 tools/lansim/run_campaign.py --code-dir vedetta --out campaign.jsonl [--quick] [--old-code-dir <the code of 0.13.1, for S30>]

Since 1.0 step P4 every run that returns the card -> MAC links (card_mac, in the shadow) also fails on a wrong link or a MAC linked to two cards (_link_problem), and the row
carries the counts of the links.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from tools.lansim import scenarios as sc  # noqa: E402


def _no_conflict_stored(r: dict) -> str:
    """A repeater lending its MAC, or a device taking the address of another, must not be stored as an IP conflict (1.0 step P3: H20 reads them)."""
    return "%d IP conflicts stored" % r["ip_conflict_rows"] if r.get("ip_conflict_rows") else ""


def _link_problem(r: dict) -> str:
    """1.0 step P4: a card linked to a MAC that is not the device at its address when it was added (the one that came later, an extender), or a MAC on two cards."""
    t = r.get("links")
    if not t or not (t["wrong"] or t["two_cards"]):
        return ""
    return "card links: %d wrong, %d MACs on two cards" % (t["wrong"], t["two_cards"])


def _link_counts(r: dict) -> dict | None:
    t = r.get("links")
    return {k: t[k] for k in ("right", "wrong", "absent", "held", "two_cards")} if t else None


def _s13l(r: dict) -> tuple[str, str]:
    if not r["before"] or r["before"][0] != r["laptop"] or r["before"][1] != "linked":
        return "fail", "the laptop was never linked: %s" % (r["before"],)
    return ("pass", "") if list(r["after"] or ()) == list(r["before"]) else ("fail", "the link changed: %s -> %s" % (r["before"], r["after"]))


def _s30(r: dict) -> tuple[str, str]:
    if not r["seed"]["right"]:
        return "fail", "no link at the seed"
    for name, t in (("seed", r["seed"]), ("end", r["links"])):
        if t["wrong"] or t["two_cards"]:
            return "fail", "%s: %d wrong, %d MACs on two cards" % (name, t["wrong"], t["two_cards"])
    return ("fail", "%d links inherited" % r["inherited"]) if r["inherited"] else ("pass", "")


def _phones_same(r: dict) -> tuple[str, str]:
    if _no_conflict_stored(r):
        return "fail", _no_conflict_stored(r)
    before, after = r["before"], r["after"]
    same = len(before) == len(after) and sorted(c["name"] for c in before) == sorted(c["name"] for c in after)
    return ("pass", "") if same else ("fail", "phone cards %d -> %d" % (len(before), len(after)))


def _s10d(r: dict) -> tuple[str, str]:
    verdict, note = _phones_same(r)
    return (verdict, note) if verdict == "pass" else ("known", "a phone without a name ends as a generic card (LAVORI_DA_FARE, 28/10): " + note)


def _s13(r: dict) -> list[tuple[str, str, str]]:
    out = []
    for pair, got in r.items():
        first, second = pair.split(" -> ")
        changed = got["before"] != got["after"]
        if _no_conflict_stored(got):
            out.append((pair, "fail", "a replacement stored as a conflict: " + _no_conflict_stored(got)))
        elif first == second:
            out.append((pair, "known" if not changed else "pass", "two devices of the same kind: same fingerprint, the name stays (known limit)"))
        else:
            out.append((pair, "pass" if changed else "fail", "" if changed else "the name of the device that left stayed"))
    return out


CHECKS = {
    "S1": lambda r: ("fail", "%d phone cards" % len(r["phones"])) if len(r["phones"]) != 1 else
          ("pass", "") if r.get("phone_link") == "right" else ("fail", "the phone's card is not linked to its MAC: " + str(r.get("phone_link"))),
    "S13L": _s13l,
    "S30": _s30,
    "S4": lambda r: ("fail", _no_conflict_stored(r)) if _no_conflict_stored(r) else
          ("pass", "") if len(r["after"]) == 1 and r["before"] and r["after"][0]["name"] == r["before"][0]["name"] else ("fail", str(r["after"])),
    "S5": lambda r: ("pass", "") if r["after"] and all(c["name"] not in {b["name"] for b in r["before"]} for c in r["after"]) else ("fail", str(r["after"])),
    "S10": _phones_same,
    "S10D": _s10d,
    "S11": lambda r: ("pass", "") if any(c.get("name") == "Portatile" for c in r["console_on"]) else ("fail", "the name chosen by the user was lost"),
    "S11B": lambda r: ("pass", "") if r["laptop_back"]["at_new_address"] else ("fail", "the laptop has no card at its new address"),
    "S11C": lambda r: ("pass", "") if r["console_on"] and all(c.get("name") not in {b.get("name") for b in r["before"]} for c in r["console_on"]) else ("fail", "the console carries the laptop's name"),
    "S12": lambda r: ("study", ""),
    "S14": lambda r: ("fail", "the fake card was linked: %s" % r["fake_card_linked"]) if r.get("fake_card_linked") else
           ("pass", "") if r["changes"]["shipped"] == ["opened", "raised", "closed"] else ("fail", str(r["changes"]["shipped"])),
    "S14B": lambda r: ("fail", "the fake card was linked: %s" % r["fake_card_linked"]) if r.get("fake_card_linked") else
            ("pass", "") if r["changes"]["shipped"] == ["opened", "raised", "closed"] else ("fail", str(r["changes"]["shipped"])),
    "S14C": lambda r: ("fail", "the fake card was linked: %s" % r["fake_card_linked"]) if r.get("fake_card_linked") else
            ("pass", "") if r["changes"]["shipped"] == ["opened", "raised"] and r["open_at_end"] == ["active"] else ("fail", str(r["changes"]["shipped"])),
    "S15": lambda r: ("pass", "") if r["judged"]["H06"]["raised"] == ["lan"] and not r["judged"]["H05"]["raised"] else ("fail", str(r["judged"])),
    "S16": lambda r: ("pass", "") if r["judged"]["H05"]["raised"] == [sc.SUBNET + ".40"] else ("fail", str(r["judged"]["H05"])),
    "S17": lambda r: ("pass", "") if r["judged"]["H07"]["raised"] == ["gateway"] else ("fail", str(r["judged"]["H07"])),
}

# (scenario, how many runs, the keyword arguments of run n): about seven hours and a half in all.
PLAN = [
    ("S14", 40, lambda n: {"seed": n + 1}), ("S14B", 2, lambda n: {}), ("S14C", 1, lambda n: {}),
    ("S1", 8, lambda n: {}), ("S4", 6, lambda n: {}), ("S5", 8, lambda n: {}),
    ("S10", 4, lambda n: {"seed": n + 1}), ("S10D", 4, lambda n: {"seed": n + 1, "dense": True}),
    ("S11", 4, lambda n: {}), ("S11B", 4, lambda n: {}), ("S11C", 4, lambda n: {}), ("S12", 2, lambda n: {}),
    ("S13", 2, lambda n: {}), ("S15", 3, lambda n: {}), ("S16", 3, lambda n: {}), ("S17", 1, lambda n: {}),
    ("S13L", 2, lambda n: {}), ("S30", 1, lambda n: {"old_code_dir": OLD_CODE_DIR}),
]
OLD_CODE_DIR: str | None = None        # set by --old-code-dir (S30)
FUNCTIONS = {"S10D": sc.s10_two_extenders, **{k: v for k, v in sc.SCENARIOS.items() if k != "S10D"}}


def run(key: str, kwargs: dict, code_dir: str) -> list[dict]:
    start = time.time()
    try:
        result = FUNCTIONS[key](code_dir, **kwargs)
    except Exception as e:                       # a run that breaks is a fail, and the campaign goes on
        return [{"scenario": key, "args": kwargs, "verdict": "fail", "note": "error: %r" % e, "seconds": round(time.time() - start)}]
    seconds = round(time.time() - start)
    if key == "S13":
        rows = [_with_links(row, result[row[0]]) for row in _s13(result)]
        return [{"scenario": key, "case": pair, "args": kwargs, "verdict": v, "note": note, "seconds": round(seconds / len(rows)), "links": links}
                for pair, v, note, links in rows]
    verdict, note, links = _with_links((key, *CHECKS[key](result)), result)[1:]
    return [{"scenario": key, "args": kwargs, "verdict": verdict, "note": note, "seconds": seconds, "links": links}]


def _with_links(row: tuple, result: dict) -> tuple:
    """(name, verdict, note) -> (name, verdict, note, the counts of the links): a link problem fails a run that passed."""
    name, verdict, note = row
    problem = _link_problem(result)
    if problem and verdict != "fail":
        verdict, note = "fail", problem
    return name, verdict, note, _link_counts(result)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--code-dir", default="vedetta")
    parser.add_argument("--out", required=True, help="the results file (JSON lines, appended)")
    parser.add_argument("--quick", action="store_true", help="one run of each scenario (to try the campaign itself)")
    parser.add_argument("--old-code-dir", help="the code of the old version (a folder holding app/), for the update and the way back of S30")
    parser.add_argument("--only", help="run these scenarios only (comma separated)")
    args = parser.parse_args()
    global OLD_CODE_DIR
    OLD_CODE_DIR = os.path.abspath(args.old_code_dir) if args.old_code_dir else None
    code_dir = os.path.abspath(args.code_dir)
    with open(args.out, "a", encoding="utf-8") as out:
        for key, runs, kwargs_of in PLAN:
            if args.only and key not in args.only.split(","):
                continue
            for n in range(1 if args.quick else runs):
                for row in run(key, kwargs_of(n), code_dir):
                    out.write(json.dumps(row) + "\n")
                    out.flush()
                    print("%-5s %-28s %-6s %s" % (row["scenario"], row.get("case", json.dumps(row["args"])), row["verdict"], row["note"][:80]), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
