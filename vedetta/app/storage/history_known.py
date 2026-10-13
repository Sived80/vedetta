"""KnownMixin: methods of History that belong together (moved out of history.py by tools/split_class.py)."""


class KnownMixin:
    # ---- known MACs (new devices on the network) ----
    def known_all(self) -> dict[str, dict]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM known_macs").fetchall()
        return {r["mac"]: dict(r) for r in rows}

    def known_set(self, mac: str, first_seen: float, ip: str | None, vendor: str | None,
                  hostname: str | None, status: str) -> None:
        with self._lock:
            self._db.execute(
                """INSERT INTO known_macs (mac, first_seen, ip, vendor, hostname, status) VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(mac) DO UPDATE SET ip = excluded.ip, vendor = excluded.vendor,
                   hostname = excluded.hostname, status = excluded.status""",
                (mac, first_seen, ip, vendor, hostname, status),
            )
            self._db.commit()

    def known_delete(self, mac: str) -> None:
        """Removes a MAC from the known ones: the app treats it as never seen."""
        with self._lock:
            self._db.execute("DELETE FROM known_macs WHERE mac = ?", (mac,))
            self._db.commit()

    def known_ignore(self, macs: list[str] | None) -> None:
        """'new' -> 'ignored' for the given MACs, or for all of them if macs is None."""
        with self._lock:
            if macs is None:
                self._db.execute("UPDATE known_macs SET status = 'ignored' WHERE status = 'new'")
            else:
                self._db.executemany("UPDATE known_macs SET status = 'ignored' WHERE status = 'new' AND mac = ?",
                                     [(m,) for m in macs])
            self._db.commit()
