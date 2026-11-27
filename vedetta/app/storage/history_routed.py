# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""RoutedMixin: the inventory by address of the networks behind the router (1.0 step P11, routedinv.py), kept on disk.

routed_seen  one row per (network, address) that answered a ping sweep: when it was first and last seen, the MAC and the name when Home
             Assistant or mDNS said them (NULL otherwise: never a MAC made up), and its status for the list of new devices ("new", "known").
routed_write is the only writer of the table (tests/check_routed_store.py); the purge of a network deletes its rows (history_purge)."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS routed_seen (
    network TEXT NOT NULL,
    ip TEXT NOT NULL,
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    mac TEXT,
    host TEXT,
    status TEXT NOT NULL DEFAULT 'known',
    PRIMARY KEY (network, ip)
);
"""
_COLUMNS = ("network", "ip", "first_seen", "last_seen", "mac", "host", "status")


class RoutedMixin:
    def routed_write(self, rows: list[dict]) -> None:
        """Writes the rows of one sweep in one transaction: a row already there (same network and address) is replaced by the new one."""
        if not rows:
            return
        with self._lock:
            self._db.executemany(
                """INSERT INTO routed_seen (network, ip, first_seen, last_seen, mac, host, status) VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(network, ip) DO UPDATE SET first_seen = excluded.first_seen, last_seen = excluded.last_seen,
                   mac = excluded.mac, host = excluded.host, status = excluded.status""",
                [tuple(r[c] for c in _COLUMNS) for r in rows])
            self._db.commit()

    def routed_rows(self, network: str | None = None) -> list[dict]:
        """The rows of one network (all of them when None)."""
        with self._lock:
            if network is None:
                rows = self._db.execute("SELECT * FROM routed_seen").fetchall()
            else:
                rows = self._db.execute("SELECT * FROM routed_seen WHERE network = ?", (network,)).fetchall()
        return [dict(r) for r in rows]

    def routed_new(self, since: float) -> list[dict]:
        """The new devices behind the router that answered since `since`, the oldest first."""
        with self._lock:
            rows = self._db.execute("SELECT * FROM routed_seen WHERE status = 'new' AND last_seen >= ? ORDER BY first_seen", (since,)).fetchall()
        return [dict(r) for r in rows]

    def routed_macs(self) -> dict[str, str]:
        """MAC -> status of the rows that have a MAC (Home Assistant said it)."""
        with self._lock:
            rows = self._db.execute("SELECT mac, status FROM routed_seen WHERE mac IS NOT NULL").fetchall()
        return {r["mac"]: r["status"] for r in rows}
