"""KnownMixin: methods of History that belong together (moved out of history.py by tools/split_class.py)."""
import time

# A private MAC (made up by the device: guests, phones that rotate it) that has no card and has not answered for this long is forgotten
# at night: otherwise every guest stays in known_macs for ever (the table is read every cycle). Seen again, it is a new device again.
PRIVATE_MAC_FORGET_DAYS = 30
# the second hex digit of the MAC has the "locally administered" bit (0x02) on: a MAC made up by the device
_FORGET_SQL = """DELETE FROM known_macs WHERE upper(substr(mac, 2, 1)) IN ('2', '3', '6', '7', 'A', 'B', 'E', 'F') AND status != 'ignored' AND first_seen < ?
    AND upper(mac) NOT IN (SELECT DISTINCT upper(mac) FROM presence_events WHERE mac IS NOT NULL)
    AND upper(mac) NOT IN (SELECT upper(mac) FROM ip_mac WHERE last_seen >= ?)"""


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

    def known_prune(self, now: float | None = None) -> int:
        """Forgets the private MACs nobody needs: no card (no presence event with that MAC), not ignored by the person, first seen
        and last answering ARP (ip_mac) more than PRIVATE_MAC_FORGET_DAYS ago. A MAC of the manufacturer is never forgotten. Returns how many."""
        cutoff = (time.time() if now is None else now) - PRIVATE_MAC_FORGET_DAYS * 86400
        with self._lock:
            cur = self._db.execute(_FORGET_SQL, (cutoff, cutoff))
            self._db.commit()
            return cur.rowcount

    def known_ignore(self, macs: list[str] | None) -> None:
        """'new' -> 'ignored' for the given MACs, or for all of them if macs is None."""
        with self._lock:
            if macs is None:
                self._db.execute("UPDATE known_macs SET status = 'ignored' WHERE status = 'new'")
            else:
                self._db.executemany("UPDATE known_macs SET status = 'ignored' WHERE status = 'new' AND mac = ?",
                                     [(m,) for m in macs])
            self._db.commit()
