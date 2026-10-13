"""ScansMixin: methods of History that belong together (moved out of history.py by tools/split_class.py)."""
import json

SCANS_KEPT_PER_DEVICE = 30


class ScansMixin:
    # ---- scans ----
    def save_scan(self, device_id: str, ts: float, result: dict) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO scans (device_id, ts, result_json) VALUES (?, ?, ?)",
                (device_id, ts, json.dumps(result, ensure_ascii=False)),
            )
            self._db.execute(
                """DELETE FROM scans WHERE device_id = ? AND id NOT IN
                   (SELECT id FROM scans WHERE device_id = ? ORDER BY ts DESC, id DESC LIMIT ?)""",
                (device_id, device_id, SCANS_KEPT_PER_DEVICE),
            )
            self._db.commit()

    # ---- blocks of a large network asked by the periodic check ----
    def scan_blocks(self) -> dict[str, float]:
        """{block: when it was last asked}."""
        with self._lock:
            rows = self._db.execute("SELECT block, ts FROM scan_blocks").fetchall()
        return {r["block"]: r["ts"] for r in rows}

    def scan_blocks_mark(self, found: dict[str, int], ts: float) -> None:
        """Notes the blocks asked now and how many devices each held."""
        with self._lock:
            self._db.executemany(
                "INSERT INTO scan_blocks (block, ts, found) VALUES (?, ?, ?) ON CONFLICT(block) DO UPDATE SET ts = excluded.ts, found = excluded.found",
                [(b, ts, int(n)) for b, n in found.items()],
            )
            self._db.commit()

    # ---- response time ----
    def record_latency(self, rows: list[tuple[str, float, float]]) -> None:
        """Samples (device_id, ts, ms), all in a single transaction."""
        with self._lock:
            self._db.executemany("INSERT INTO latency (device_id, ts, ms) VALUES (?, ?, ?)", rows)
            self._db.commit()

    def latency_points(self, device_id: str, since: float, until: float) -> list[tuple[float, float]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT ts, ms FROM latency WHERE device_id = ? AND ts >= ? AND ts <= ? ORDER BY ts",
                (device_id, since, until),
            ).fetchall()
        return [(r["ts"], r["ms"]) for r in rows]
