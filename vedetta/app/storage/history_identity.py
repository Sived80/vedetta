"""IdentityMixin: the history of what Vedetta called each card (name and brand), so the card can say «the name went from android-7f3a
to Pixel of Anna on 12/11, from the Bonjour name». One row per real change (identity_changes.py decides which), kept 90 days like the
presence; the purge of a network and the merge of two cards treat it like the other tables of a card."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS identity_change (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    ts REAL NOT NULL,
    field TEXT NOT NULL,
    old TEXT,
    new TEXT,
    source TEXT
);
CREATE INDEX IF NOT EXISTS idx_identity_device_ts ON identity_change (device_id, ts);
"""
RETENTION_DAYS = 90


class IdentityMixin:
    def identity_record(self, rows: list[dict]) -> None:
        """Writes the changes of one cycle in one transaction ({device_id, ts, field, old, new, source})."""
        if not rows:
            return
        with self._lock:
            self._db.executemany("INSERT INTO identity_change (device_id, ts, field, old, new, source) VALUES (?, ?, ?, ?, ?, ?)",
                                 [(r["device_id"], r["ts"], r["field"], r.get("old"), r.get("new"), r.get("source")) for r in rows])
            self._db.commit()

    def identity_changes(self, device_id: str, limit: int = 20) -> list[dict]:
        """The latest changes of a card, newest first."""
        with self._lock:
            rows = self._db.execute("SELECT ts, field, old, new, source FROM identity_change WHERE device_id = ? ORDER BY ts DESC, id DESC LIMIT ?",
                                    (device_id, limit)).fetchall()
        return [dict(r) for r in rows]

    def prune_identity(self, now: float) -> None:
        with self._lock:
            self._db.execute("DELETE FROM identity_change WHERE ts < ?", (now - RETENTION_DAYS * 86400,))
            self._db.commit()
