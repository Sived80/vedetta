"""A campaign on the virtual LAN: every scenario run again and again, with other seeds where the scenario takes one, each run judged by what the scenario promises (pass, fail, a known
limit that is on the list, or a study that has no right answer). One line of JSON per run goes to the results file as soon as the run ends, so a campaign stopped half way keeps
what it did. Linux and root only, a few hours:

    python3 tools/lansim/run_campaign.py --code-dir vedetta --out campaign.jsonl [--quick] [--old-code-dir <the code of 0.13.1, for S30>] [--only S1,S4] [--jobs 4]

Since 1.0 step P4 every run that returns the card -> MAC links (card_mac) also fails on a wrong link or a MAC linked to two cards (_link_problem), and the row carries the
counts of the links; since step P5 "wrong" counts the links the app may use (the others are in wrong_stored), and the row carries what a run measured besides (extra).

The runs mostly wait for Vedetta's cycles, so with --jobs N they go N at a time: each in a network namespace of its own (lsrun-a, lsrun-b, ...) with its own letter for the
names of its machines (LANSIM_RUN, see lan.py). The longest scenarios start first; the lines of the results file come in the order the runs end.
"""
import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

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
    return {k: t.get(k, 0) for k in ("right", "wrong", "wrong_stored", "absent", "held", "two_cards")} if t else None


def _extra(r: dict) -> dict | None:
    """What a run measured besides its verdict (P5): the share of time online of the phones behind the extenders, how long a card took to follow its device."""
    got = {k: r[k] for k in ("online_share", "followed_s", "alerts") if isinstance(r, dict) and k in r}
    return got or None


def _s13l(r: dict) -> tuple[str, str]:
    if not r["before"] or r["before"][0] != r["laptop"] or r["before"][1] != "linked":
        return "fail", "the laptop was never linked: %s" % (r["before"],)
    if list(r["after"] or ())[:3] != list(r["before"])[:3]:
        return "fail", "the link changed: %s -> %s" % (r["before"], r["after"])
    seen, first = r["seen"], r["card_before"] or {}
    if not seen or seen[-1] is None or seen[-1]["online"]:
        return "fail", "the laptop's card did not go offline"
    if any(c is None or any(c[k] != first.get(k) for k in ("name", "brand", "type")) for c in seen):
        return "fail", "the laptop's card changed name, brand or type: %s" % seen
    return ("pass", "") if r["cards_at_address"] == 1 else ("fail", "%d cards at the address (1A: the console has none until P7)" % r["cards_at_address"])


def _s11l(r: dict) -> tuple[str, str]:
    if not r["usable"]:
        return "fail", "the laptop's link never became usable"
    end = r["card_end"] or {}
    if r["followed_s"] is None or end.get("ip") != r["new_address"] or not end.get("online"):
        return "fail", "the card did not follow the laptop: %s" % end
    if any(c and c.get("name") != "Portatile" for c in r["seen"]) or end.get("name") != "Portatile":
        return "fail", "the card showed another name: %s" % [c and c.get("name") for c in r["seen"]]
    return ("pass", "") if r["cards_at_old_address"] == 0 else ("fail", "a card stayed at the old address")


def _s31(r: dict) -> tuple[str, str]:
    if not r["usable"]:
        return "fail", "the links never became usable"
    for k, ip in r["want"].items():
        c = r["end"].get(k) or {}
        if c.get("ip") != ip or c.get("name") != r["names"][k] or not c.get("online"):
            return "fail", "%s: %s, wanted %s" % (k, c, ip)
    if r["offline_seen"]:
        return "fail", "a card went offline %d times" % r["offline_seen"]
    return ("pass", "") if r["alerts"] == 2 else ("fail", "%d notices of a changed address" % r["alerts"])


def _s32(r: dict) -> tuple[str, str]:
    if not r["usable"]:
        return "fail", "the link never became usable"
    if r["followed_s"] is None or r["followed_s"] > 360 or (r["card_end"] or {}).get("ip") != r["new_address"]:
        return "fail", "the card did not follow within a full sweep and a cycle: %s s" % r["followed_s"]
    return ("pass", "") if r["alerts"] == 1 else ("fail", "%d notices of a changed address" % r["alerts"])


def _s35(r: dict) -> tuple[str, str]:
    """P7: the TV listed as new, then away for longer than a full sweep: still listed in at least 90% of the cycles."""
    if r["first_listed_s"] is None:
        return "fail", "the TV was never listed as new"
    share = round(sum(1 for x in r["listed_away"] if x) / len(r["listed_away"]), 3) if r["listed_away"] else 0.0
    return ("pass", "") if share >= 0.9 else ("fail", "listed in %s of the cycles away" % share)


def _s36(r: dict) -> tuple[str, str]:
    """P7: the console at the linked laptop's address is listed as new."""
    if not r["usable"]:
        return "fail", "the laptop's link never became usable"
    return ("pass", "") if r["console_listed_s"] is not None else ("fail", "the console stayed hidden behind the laptop's card")


def _s33(r: dict) -> tuple[str, str]:
    if not r["usable"]:
        return "fail", "the printer's link never became usable"
    if not r["offline_before"] or not r["offered"] or not r["sent"]:
        return "fail", "offline %s, offered %s, sent %s" % (r["offline_before"], r["offered"], r["sent"])
    end = r["card_end"] or {}
    if end.get("id") != r["card_id"] or end.get("name") != r["name"] or not end.get("online"):
        return "fail", "the card after the gesture: %s" % end
    return ("pass", "") if r["row_end"] and r["row_end"][0] == r["new_mac"] and r["row_end"][2] == "user" else ("fail", "the link: %s" % r["row_end"])


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
    "S11L": _s11l,
    "S31": _s31,
    "S32": _s32,
    "S33": _s33,
    "S35": _s35,
    "S36": _s36,
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
    ("S11L", 2, lambda n: {}), ("S31", 2, lambda n: {}), ("S32", 2, lambda n: {}), ("S33", 1, lambda n: {}),
    ("S35", 2, lambda n: {}), ("S36", 2, lambda n: {}),
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
    return [{"scenario": key, "args": kwargs, "verdict": verdict, "note": note, "seconds": seconds, "links": links, "extra": _extra(result)}]


def _with_links(row: tuple, result: dict) -> tuple:
    """(name, verdict, note) -> (name, verdict, note, the counts of the links): a link problem fails a run that passed."""
    name, verdict, note = row
    problem = _link_problem(result)
    if problem and verdict != "fail":
        verdict, note = "fail", problem
    return name, verdict, note, _link_counts(result)


SLOW_FIRST = ("S17", "S15", "S16")       # about 95, 20 and 18 minutes: started first, so the campaign does not end waiting on one long run
LETTERS = "abcdefghijklmnop"
# The ceiling: never more runs at once than half the processor threads, and never more than 8, so the PC stays usable; every run also has a lower priority (nice 10).
MAX_JOBS = max(1, min(8, (os.cpu_count() or 2) // 2))


def jobs(quick: bool, slow_first: bool = False) -> list[tuple[str, dict]]:
    """Every run of the plan as (scenario, keyword arguments) in the order of the plan; with slow_first the longest scenarios go first (stable sort: the rest keeps its order)."""
    out = [(key, kwargs_of(n)) for key, runs, kwargs_of in PLAN for n in range(1 if quick else runs)]
    return sorted(out, key=lambda job: SLOW_FIRST.index(job[0]) if job[0] in SLOW_FIRST else len(SLOW_FIRST)) if slow_first else out


def _in_namespace(letter: str, key: str, kwargs: dict, code_dir: str) -> list[dict]:
    """One run inside the namespace lsrun-<letter>, as a child process that prints its rows as one line of JSON."""
    start = time.time()
    env = {**os.environ, "LANSIM_RUN": letter}
    cmd = ["nice", "-n", "10", "ip", "netns", "exec", "lsrun-" + letter, sys.executable, "-B", os.path.abspath(__file__), "--one", key, "--kwargs", json.dumps(kwargs), "--code-dir", code_dir]
    done = subprocess.run(cmd, env=env, capture_output=True, text=True)
    lines = [line for line in done.stdout.splitlines() if line.startswith("[")]
    if done.returncode != 0 or not lines:
        return [{"scenario": key, "args": kwargs, "verdict": "fail", "note": "error: exit %d %s" % (done.returncode, done.stderr.strip()[-300:]), "seconds": round(time.time() - start)}]
    return json.loads(lines[-1])


def _write(out, rows: list[dict], lock: threading.Lock) -> None:
    with lock:
        for row in rows:
            out.write(json.dumps(row) + "\n")
            out.flush()
            print("%-5s %-28s %-6s %s" % (row["scenario"], row.get("case", json.dumps(row["args"])), row["verdict"], row["note"][:80]), flush=True)


def _parallel(todo: list[tuple[str, dict]], n: int, code_dir: str, out) -> None:
    letters: queue.Queue = queue.Queue()
    for letter in LETTERS[:n]:
        subprocess.run(["ip", "netns", "del", "lsrun-" + letter], capture_output=True)
        subprocess.run(["ip", "netns", "add", "lsrun-" + letter], check=True)
        subprocess.run(["ip", "-n", "lsrun-" + letter, "link", "set", "lo", "up"], check=True)
        letters.put(letter)
    lock = threading.Lock()

    def one(job: tuple[str, dict]) -> None:
        letter = letters.get()
        try:
            _write(out, _in_namespace(letter, job[0], job[1], code_dir), lock)
        finally:
            letters.put(letter)
    try:
        with ThreadPoolExecutor(max_workers=n) as pool:
            list(pool.map(one, todo))
    finally:
        for letter in LETTERS[:n]:
            subprocess.run(["ip", "netns", "del", "lsrun-" + letter], capture_output=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--code-dir", default="vedetta")
    parser.add_argument("--out", help="the results file (JSON lines, appended)")
    parser.add_argument("--quick", action="store_true", help="one run of each scenario (to try the campaign itself)")
    parser.add_argument("--old-code-dir", help="the code of the old version (a folder holding app/), for the update and the way back of S30")
    parser.add_argument("--only", help="run these scenarios only (comma separated)")
    parser.add_argument("--jobs", type=int, default=1, help="runs at the same time, each in a namespace of its own (1 = one after the other, as always)")
    parser.add_argument("--one", help=argparse.SUPPRESS)            # the child of --jobs: one run, its rows printed as one line of JSON
    parser.add_argument("--kwargs", default="{}", help=argparse.SUPPRESS)
    args = parser.parse_args()
    global OLD_CODE_DIR
    OLD_CODE_DIR = os.path.abspath(args.old_code_dir) if args.old_code_dir else None
    code_dir = os.path.abspath(args.code_dir)
    if args.one:
        print(json.dumps(run(args.one, json.loads(args.kwargs), code_dir)), flush=True)
        return 0
    if not args.out:
        parser.error("--out is required")
    if not 1 <= args.jobs <= MAX_JOBS:
        parser.error("--jobs must be between 1 and %d on this machine (the ceiling: half the processor threads, at most 8)" % MAX_JOBS)
    with open(args.out, "a", encoding="utf-8") as out:
        todo = [job for job in jobs(args.quick, slow_first=args.jobs > 1) if not args.only or job[0] in args.only.split(",")]
        if args.jobs == 1:
            lock = threading.Lock()
            for key, kwargs in todo:
                _write(out, run(key, kwargs, code_dir), lock)
        else:
            _parallel(todo, args.jobs, code_dir, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
