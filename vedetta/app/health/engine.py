"""The judge: it runs the detector of every rule that is not a draft and keeps the findings. A finding is «tentative» until it is seen for min_cycles judgments, then «active»; it is closed after clear_cycles judgments without it. A tentative that is not
seen again goes away without a trace (one flicker opens nothing). The findings of a rule in shadow are marked so, and the page does not show them."""
from dataclasses import dataclass, field

from ..applog import logger
from . import detectors, matrix


@dataclass
class Finding:
    rule: str
    subject: str
    state: str                         # tentative | active | closed | dropped (a tentative that was not seen again)
    severity: str
    first_seen: float
    last_seen: float
    hits: int = 1
    evidence: dict = field(default_factory=dict)
    shadow: bool = True
    quiet: int = 0                     # judgments in a row without it


@dataclass(frozen=True)
class Change:
    change: str                        # opened | raised | closed | dropped
    finding: Finding


class Engine:
    def __init__(self, rows: list[dict] | None = None):
        self._rows = [r for r in (matrix.load() if rows is None else rows) if r["status"] != "draft"]
        self._found: dict[tuple[str, str], Finding] = {}

    def findings(self) -> list[Finding]:
        return list(self._found.values())

    def judge(self, signals: dict, now: float) -> list[Change]:
        changes: list[Change] = []
        for row in self._rows:
            try:
                evidence = detectors.FAMILIES[row["family"]](signals, row["params"])
            except Exception:
                logger.debug("Health rule %s not judged", row["id"], exc_info=True)
                continue
            changes += self._apply(row, evidence, now)
        return changes

    def _apply(self, row: dict, evidence: list[detectors.Evidence], now: float) -> list[Change]:
        seen = {e.subject: e for e in evidence}
        changes = [c for e in seen.values() for c in self._seen(row, e, now)]
        for key in [k for k in self._found if k[0] == row["id"] and k[1] not in seen]:
            changes += self._missed(row, key)
        return changes

    def _seen(self, row: dict, e: detectors.Evidence, now: float) -> list[Change]:
        key = (row["id"], e.subject)
        found = self._found.get(key)
        if found is None:
            immediate = row["params"]["min_cycles"] <= 1       # a rule that needs one sight only (an event that has already happened) is active at once
            self._found[key] = found = Finding(row["id"], e.subject, "active" if immediate else "tentative", row["severity"], now, now, evidence=e.data, shadow=row["status"] == "shadow")
            return [Change("raised" if immediate else "opened", found)]
        found.hits += 1
        found.quiet, found.last_seen, found.evidence = 0, now, e.data
        if found.state == "tentative" and found.hits >= row["params"]["min_cycles"]:
            found.state = "active"
            return [Change("raised", found)]
        return []

    def _missed(self, row: dict, key: tuple[str, str]) -> list[Change]:
        found = self._found[key]
        found.quiet += 1
        if found.quiet < row["params"]["clear_cycles"]:
            return []
        del self._found[key]
        was_tentative = found.state == "tentative"
        found.state = "dropped" if was_tentative else "closed"
        return [Change("dropped" if was_tentative else "closed", found)]
