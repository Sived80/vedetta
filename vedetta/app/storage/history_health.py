"""HealthMixin: the findings of the network health (health/) kept on disk, so a restart does not lose the record of what was seen.

health_finding  one row per episode of a problem: (rule, subject, first_seen) is the key, the row is updated while the episode goes on and keeps its end when it closes.
                The evidence holds counts only (never an address or a name)."""
import json
import time

HEALTH_RETENTION_DAYS = 90

SCHEMA = """
CREATE TABLE IF NOT EXISTS health_finding (
    rule TEXT NOT NULL,
    subject TEXT NOT NULL,
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    state TEXT NOT NULL,
    severity TEXT NOT NULL,
    hits INTEGER NOT NULL,
    evidence TEXT NOT NULL,
    shadow INTEGER NOT NULL,
    PRIMARY KEY (rule, subject, first_seen)
);
CREATE INDEX IF NOT EXISTS idx_health_finding_seen ON health_finding (last_seen);
"""


class HealthMixin:
    def record_finding(self, *, rule: str, subject: str, state: str, severity: str, first_seen: float, last_seen: float, hits: int, evidence: dict, shadow: bool) -> None:
        with self._lock:
            self._db.execute(
                """INSERT INTO health_finding (rule, subject, first_seen, last_seen, state, severity, hits, evidence, shadow) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (rule, subject, first_seen) DO UPDATE SET last_seen = excluded.last_seen, state = excluded.state, severity = excluded.severity,
                   hits = excluded.hits, evidence = excluded.evidence, shadow = excluded.shadow""",
                (rule, subject, first_seen, last_seen, state, severity, hits, json.dumps(evidence, sort_keys=True), int(shadow)))
            self._db.commit()

    def health_findings(self, since: float) -> list[dict]:
        """The findings seen after `since`, the newest first."""
        with self._lock:
            rows = self._db.execute("SELECT * FROM health_finding WHERE last_seen >= ? ORDER BY first_seen DESC", (since,)).fetchall()
        return [{**dict(r), "evidence": json.loads(r["evidence"]), "shadow": bool(r["shadow"])} for r in rows]

    def prune_health(self) -> None:
        with self._lock:
            self._db.execute("DELETE FROM health_finding WHERE last_seen < ?", (time.time() - HEALTH_RETENTION_DAYS * 86400,))
            self._db.commit()
