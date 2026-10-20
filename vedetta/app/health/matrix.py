"""The matrix of the rules: loaded from matrix.json and checked in plain Python (no extra library). A bad row is refused with its id and the name of the field, so a mistake in the data is found at start and by the tests, not in the field."""
import json
from pathlib import Path

from . import detectors

PATH = Path(__file__).with_name("matrix.json")
REQUIRED = ("id", "family", "tile", "params", "signals", "scope", "class", "severity", "message_key", "remedy_key", "detectability", "status", "since", "existence")
TILES = ("addr", "drop", "boot", "lat")          # the four tiles of the page: addresses, drops, restarts, latency
SEVERITIES = ("info", "warning", "critical")
STATUSES = ("draft", "shadow", "active")
DETECTABILITY = ("D1", "D2", "D3")
GRADES = ("A", "B", "C")


def _fail(row: dict, field: str, why: str) -> None:
    raise ValueError("health rule %s: field %s %s" % (row.get("id", "?"), field, why))


ENUMS = {"severity": SEVERITIES, "status": STATUSES, "detectability": DETECTABILITY, "tile": TILES}


def _check_sources(row: dict) -> None:
    existence = row["existence"]
    if not isinstance(existence, dict) or existence.get("grade") not in GRADES:
        _fail(row, "existence", "needs a grade A, B or C")
    if not all(str(s.get("link", "")).startswith("https://") for s in existence.get("sources", [])):
        _fail(row, "existence.sources.link", "must be an https address")


def _check_params(row: dict) -> None:
    for name in ("min_cycles", "clear_cycles"):
        value = row["params"].get(name)
        if not isinstance(value, int) or value < 1:
            _fail(row, name, "must be a whole number of at least 1")


def _check_row(row: dict) -> None:
    missing = [name for name in REQUIRED if name not in row]
    if missing:
        _fail(row, missing[0], "is missing")
    if row["family"] not in detectors.FAMILIES:
        _fail(row, "family", "has no detector (%s)" % row["family"])
    for name, allowed in ENUMS.items():
        if row[name] not in allowed:
            _fail(row, name, "must be one of %s" % ", ".join(allowed))
    if not isinstance(row["signals"], list):
        _fail(row, "signals", "must be a list")
    _check_params(row)
    _check_sources(row)


def validate(rows: list[dict]) -> list[dict]:
    seen = set()
    for row in rows:
        _check_row(row)
        if row["id"] in seen:
            _fail(row, "id", "appears twice")
        seen.add(row["id"])
    return rows


def load(path: Path = PATH) -> list[dict]:
    return validate(json.loads(path.read_text(encoding="utf-8")))
