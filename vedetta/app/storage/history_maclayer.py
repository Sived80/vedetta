"""MacLayerMixin: the tables of the single MAC layer (moved out of history.py's class by design, see maclayer.py).

ip_mac       one row per (ip, mac, source): when first and last observed and how many times. Written in one transaction per cycle.
mac_class    phase 2: what kind of MAC it is (normal, lender, multi-address host...). Empty for now.
ip_conflict  phase 3: IP addresses answered by different MACs over time. Empty for now."""
import time

MACLAYER_RETENTION_DAYS = 90
SESSION_GAP_S = 600       # a gap longer than this between two observations of (ip, mac, source) starts a new session

SCHEMA = """
CREATE TABLE IF NOT EXISTS ip_mac (
    ip TEXT NOT NULL,
    mac TEXT NOT NULL,
    source TEXT NOT NULL,
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    seen_count INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (ip, mac, source)
);
CREATE INDEX IF NOT EXISTS idx_ip_mac_mac ON ip_mac (mac, last_seen);
CREATE TABLE IF NOT EXISTS ip_mac_session (
    ip TEXT NOT NULL,
    mac TEXT NOT NULL,
    source TEXT NOT NULL,
    start REAL NOT NULL,
    end REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ip_mac_session ON ip_mac_session (ip, mac, source, end);
CREATE INDEX IF NOT EXISTS idx_ip_mac_session_mac ON ip_mac_session (mac, end);
CREATE TABLE IF NOT EXISTS ip_flip (
    ip TEXT NOT NULL,
    old_mac TEXT NOT NULL,
    new_mac TEXT NOT NULL,
    ts REAL NOT NULL,
    gap REAL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_ip_flip ON ip_flip (ip, ts);
CREATE TABLE IF NOT EXISTS mac_class (
    mac TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    detail TEXT,
    updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS ip_conflict (
    ip TEXT NOT NULL,
    macs TEXT NOT NULL,
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    PRIMARY KEY (ip, macs)
);
"""


class MacLayerMixin:
    def _maclayer_migrate(self) -> None:
        """Columns added after the first deploy (CREATE TABLE IF NOT EXISTS does not add them to an existing table)."""
        try:
            self._db.execute("ALTER TABLE ip_flip ADD COLUMN gap REAL DEFAULT 0")
            self._db.commit()
        except Exception:
            pass                                    # the column is already there

    @staticmethod
    def _merge_observations(observations) -> dict[tuple, list]:
        """{(ip, mac, source): [first ts, last ts]} of the batch, in order of first appearance."""
        merged: dict[tuple, list] = {}
        for o in observations:
            row = merged.setdefault((o.ip, o.mac, o.source), [o.ts, o.ts])
            row[0], row[1] = min(row[0], o.ts), max(row[1], o.ts)
        return merged

    def _record_flip(self, ip: str, mac: str, first: float) -> None:
        """If another MAC answered this address last time (by ARP), writes the change into ip_flip."""
        prev = self._db.execute("SELECT mac, last_seen FROM ip_mac WHERE ip = ? AND source = 'arp' ORDER BY last_seen DESC LIMIT 1", (ip,)).fetchone()
        if prev and prev[0] != mac:
            self._db.execute("INSERT INTO ip_flip (ip, old_mac, new_mac, ts, gap) VALUES (?, ?, ?, ?, ?)", (ip, prev[0], mac, first, max(0.0, first - prev[1])))

    def _record_flips(self, merged: dict[tuple, list]) -> None:
        """A change of the MAC answering an address: only ARP observations count, oldest first."""
        for (ip, mac, src), (first, _last) in sorted(merged.items(), key=lambda kv: kv[1][0]):
            if src == "arp":
                self._record_flip(ip, mac, first)

    def _upsert_pairs(self, merged: dict[tuple, list]) -> None:
        self._db.executemany(
            """INSERT INTO ip_mac (ip, mac, source, first_seen, last_seen, seen_count) VALUES (?, ?, ?, ?, ?, 1)
               ON CONFLICT (ip, mac, source) DO UPDATE SET last_seen = MAX(last_seen, excluded.last_seen), seen_count = seen_count + 1""",
            [(ip, mac, src, first, last) for (ip, mac, src), (first, last) in merged.items()])

    def _update_sessions(self, merged: dict[tuple, list]) -> None:
        """Sessions: when was each (address, MAC, source) really active; a gap longer than SESSION_GAP_S starts a new one."""
        for (ip, mac, src), (first, last) in merged.items():
            row = self._db.execute("SELECT rowid, end FROM ip_mac_session WHERE ip = ? AND mac = ? AND source = ? ORDER BY end DESC LIMIT 1",
                                   (ip, mac, src)).fetchone()
            if row and first - row[1] <= SESSION_GAP_S:
                self._db.execute("UPDATE ip_mac_session SET end = MAX(end, ?) WHERE rowid = ?", (last, row[0]))
            else:
                self._db.execute("INSERT INTO ip_mac_session (ip, mac, source, start, end) VALUES (?, ?, ?, ?, ?)", (ip, mac, src, first, last))

    def observe(self, observations) -> int:
        """Writes a batch of observations (maclayer.Observation) in a single transaction; a repeated (ip, mac, source) only moves
        last_seen forward and counts once more. Returns how many distinct rows were touched."""
        merged = self._merge_observations(observations)
        if not merged:
            return 0
        with self._lock:
            self._record_flips(merged)
            self._upsert_pairs(merged)
            self._update_sessions(merged)
            self._db.commit()
        return len(merged)

    def rows(self, since: float = 0.0) -> list[dict]:
        """The ip_mac rows seen after `since`, as the classifier takes them."""
        with self._lock:
            rows = self._db.execute("SELECT ip, mac, source, first_seen, last_seen, seen_count FROM ip_mac WHERE last_seen >= ?", (since,)).fetchall()
        return [dict(zip(("ip", "mac", "source", "first_seen", "last_seen", "seen_count"), r)) for r in rows]

    def flips(self, since: float = 0.0) -> list[dict]:
        """Every change of the MAC that answers an address after `since`: {ip, old, new, ts}."""
        with self._lock:
            rows = self._db.execute("SELECT ip, old_mac, new_mac, ts, gap FROM ip_flip WHERE ts >= ? ORDER BY ts", (since,)).fetchall()
        return [dict(zip(("ip", "old", "new", "ts", "gap"), r)) for r in rows]

    def sessions(self, since: float = 0.0) -> list[dict]:
        """Every activity session after `since`: {ip, mac, source, start, end}."""
        with self._lock:
            rows = self._db.execute("SELECT ip, mac, source, start, end FROM ip_mac_session WHERE end >= ? ORDER BY start", (since,)).fetchall()
        return [dict(zip(("ip", "mac", "source", "start", "end"), r)) for r in rows]

    def macs_for_ip(self, ip: str, since: float = 0.0) -> list[dict]:
        """Every MAC seen at that address after `since`, most recent first (all sources)."""
        with self._lock:
            rows = self._db.execute(
                "SELECT mac, source, first_seen, last_seen, seen_count FROM ip_mac WHERE ip = ? AND last_seen >= ? ORDER BY last_seen DESC", (ip, since)).fetchall()
        return [dict(zip(("mac", "source", "first_seen", "last_seen", "seen_count"), r)) for r in rows]

    def ips_for_mac(self, mac: str, since: float = 0.0) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT ip, source, first_seen, last_seen, seen_count FROM ip_mac WHERE mac = ? AND last_seen >= ? ORDER BY last_seen DESC", (mac, since)).fetchall()
        return [dict(zip(("ip", "source", "first_seen", "last_seen", "seen_count"), r)) for r in rows]

    def mac_ip_counts(self, since: float = 0.0) -> dict[str, int]:
        """MAC -> how many distinct addresses it was seen at after `since` (the input of phase 2: lender candidates)."""
        with self._lock:
            rows = self._db.execute("SELECT mac, COUNT(DISTINCT ip) FROM ip_mac WHERE last_seen >= ? GROUP BY mac", (since,)).fetchall()
        return dict(rows)

    def maclayer_summary(self, window_days: int = 7) -> dict:
        """Counts only, never an address or a MAC (it goes into the export for the developer): rows per source, how many MACs and addresses,
        and how the MACs spread over addresses and the addresses over MACs in the window (1, 2, 3, 4+)."""
        since = time.time() - window_days * 86400

        def spread(group: str, count: str) -> dict:
            rows = self._db.execute(
                f"SELECT MIN(n, 4), COUNT(*) FROM (SELECT COUNT(DISTINCT {count}) AS n FROM ip_mac WHERE last_seen >= ? GROUP BY {group}) GROUP BY MIN(n, 4)", (since,)).fetchall()
            return {("4+" if n == 4 else str(n)): c for n, c in rows}

        with self._lock:
            by_source = dict(self._db.execute("SELECT source, COUNT(*) FROM ip_mac WHERE last_seen >= ? GROUP BY source", (since,)).fetchall())
            macs, ips = self._db.execute("SELECT COUNT(DISTINCT mac), COUNT(DISTINCT ip) FROM ip_mac WHERE last_seen >= ?", (since,)).fetchone()
            oldest = self._db.execute("SELECT MIN(first_seen) FROM ip_mac").fetchone()[0]
            return {"window_days": window_days, "rows_by_source": by_source, "macs": macs, "addresses": ips,
                    "addresses_per_mac": spread("mac", "ip"), "macs_per_address": spread("ip", "mac"),
                    "history_days": round((time.time() - oldest) / 86400, 1) if oldest else 0}

    def prune_maclayer(self) -> None:
        cutoff = time.time() - MACLAYER_RETENTION_DAYS * 86400
        with self._lock:
            self._db.execute("DELETE FROM ip_mac WHERE last_seen < ?", (cutoff,))
            self._db.execute("DELETE FROM ip_conflict WHERE last_seen < ?", (cutoff,))
            self._db.execute("DELETE FROM ip_mac_session WHERE end < ?", (cutoff,))
            self._db.execute("DELETE FROM ip_flip WHERE ts < ?", (cutoff,))
            self._db.commit()
