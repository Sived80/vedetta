"""The catalogue of behaviours that make a device in a network differ from a generic client (tests/data/behavior_matrix.json), and what is still not tested.
It is data: to add a case add a row (a behaviour, an overlap) and, if it can be run, a scenario in tests/behavior_scenarios.py.
    python tools/behavior_matrix.py            summary and what is not covered
    python tools/behavior_matrix.py pairs      overlaps still to decide (behaviours that perturb the same signal)
    python tools/behavior_matrix.py add-overlap <id> <id>   adds an empty overlap to fill in"""
import json
import sys
from itertools import combinations
from pathlib import Path

MATRIX = Path(__file__).resolve().parent.parent / "tests" / "data" / "behavior_matrix.json"
VERIFIED = {"web", "export", "web+export", "gap"}


def load(path: Path = MATRIX) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def problems(matrix: dict) -> list[str]:
    """Everything wrong with the shape of the matrix (unknown ids, axes, evidence level, missing sources)."""
    ids = [b["id"] for b in matrix["behaviors"]]
    found = [f"duplicate id {i}" for i in set(ids) if ids.count(i) > 1]
    for b in matrix["behaviors"]:
        found += [f"{b['id']}: unknown axis {a}" for a in b["perturbs"] if a not in matrix["axes"]]
        found += [f"{b['id']}: {k} missing" for k in ("name", "what", "risk", "expected", "category") if not b.get(k)]
        found += _evidence_problems(b["id"], b)
    for o in matrix["overlaps"]:
        found += [f"overlap {o['ids']}: unknown id {i}" for i in o["ids"] if i not in ids]
        found += _evidence_problems("overlap " + "+".join(o["ids"]), o)
    return found


def _evidence_problems(label: str, row: dict) -> list[str]:
    found = []
    if row.get("verified") not in VERIFIED:
        found.append(f"{label}: verified must be one of {sorted(VERIFIED)}")
    if row.get("verified", "").startswith("web") and not row.get("sources"):
        found.append(f"{label}: marked from the web but has no source")
    return found


def candidate_pairs(matrix: dict) -> list[tuple[str, str, list[str]]]:
    """Pairs of behaviours that perturb a common signal: they can mask each other, so each deserves a decision."""
    return [(a["id"], b["id"], sorted(set(a["perturbs"]) & set(b["perturbs"])))
            for a, b in combinations(matrix["behaviors"], 2) if set(a["perturbs"]) & set(b["perturbs"])]


def decided(matrix: dict) -> set[frozenset]:
    return {frozenset(o["ids"]) for o in matrix["overlaps"]}


def undecided_pairs(matrix: dict) -> list[tuple[str, str, list[str]]]:
    done = decided(matrix)
    return [p for p in candidate_pairs(matrix) if frozenset(p[:2]) not in done]


def untested(matrix: dict) -> list[str]:
    """Rows without a check (a scenario or a test file): the cases still to write."""
    rows = [(b["id"], b) for b in matrix["behaviors"]] + [("+".join(o["ids"]), o) for o in matrix["overlaps"]]
    return [name for name, row in rows if not row.get("check")]


def add_overlap(path: Path, first: str, second: str) -> None:
    matrix = load(path)
    matrix["overlaps"].append({"ids": [first, second], "risk": "", "expected": "", "check": None, "verified": "gap"})
    save(matrix, path)


def save(matrix: dict, path: Path = MATRIX) -> None:
    """Writes the matrix with one row per line (readable and easy to diff)."""
    def rows(items):
        return ",\n".join("    " + json.dumps(i, ensure_ascii=False) for i in items)
    axes = json.dumps(matrix["axes"], ensure_ascii=False, indent=4).replace("\n", "\n  ")
    text = '{\n  "schema": %d,\n  "axes": %s,\n  "behaviors": [\n%s\n  ],\n  "overlaps": [\n%s\n  ]\n}\n'
    path.write_text(text % (matrix["schema"], axes, rows(matrix["behaviors"]), rows(matrix["overlaps"])), encoding="utf-8", newline="\n")


def main(argv: list[str]) -> None:
    matrix = load()
    if argv[:1] == ["add-overlap"]:
        return add_overlap(MATRIX, argv[1], argv[2])
    if argv[:1] == ["pairs"]:
        for a, b, axes in undecided_pairs(matrix):
            print(f"{a} + {b}  [{', '.join(axes)}]")
        return None
    print(f"{len(matrix['behaviors'])} behaviours, {len(matrix['overlaps'])} overlaps decided of {len(candidate_pairs(matrix))} possible, "
          f"{len(untested(matrix))} rows without a check, {sum(b['verified'] == 'gap' for b in matrix['behaviors'])} behaviours without a source")
    print("without a check:", ", ".join(untested(matrix)))
    return None


if __name__ == "__main__":
    main(sys.argv[1:])
