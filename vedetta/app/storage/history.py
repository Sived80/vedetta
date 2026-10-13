"""The database of the service (vedetta.db, SQLite): presence history, scans, known devices, the memory of MAC addresses and the MAC layer.
History is one class assembled from mixins, one per theme (history_presence, history_known, history_macs, history_maclayer, history_scans)."""
import sqlite3
import threading
import time
from pathlib import Path

from ..paths import DATA_DIR as CONFIG_DIR
from .history_presence import PresenceMixin
from .history_known import KnownMixin
from .history_macs import MacMemoryMixin
from .history_scans import ScansMixin
from .history_maclayer import MacLayerMixin, SCHEMA as _MACLAYER_SCHEMA
DB_PATH = CONFIG_DIR / "vedetta.db"

PRESENCE_RETENTION_DAYS = 90
LATENCY_RETENTION_DAYS = 7
SHADOW_RETENTION_DAYS = 90

_SCHEMA = """
CREATE TABLE IF NOT EXISTS presence_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    ip TEXT,
    mac TEXT,
    online INTEGER NOT NULL,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_presence_device_ts ON presence_events (device_id, ts);

CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    ts REAL NOT NULL,
    result_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scans_device_ts ON scans (device_id, ts);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS latency (
    device_id TEXT NOT NULL,
    ts REAL NOT NULL,
    ms REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_latency_device_ts ON latency (device_id, ts);

CREATE TABLE IF NOT EXISTS known_macs (
    mac TEXT PRIMARY KEY,
    first_seen REAL,
    ip TEXT,
    vendor TEXT,
    hostname TEXT,
    status TEXT NOT NULL
);

-- The /24 blocks of a large network the periodic check has asked, and when (see scan/arpplan.py): it goes round them one by one.
CREATE TABLE IF NOT EXISTS scan_blocks (
    block TEXT PRIMARY KEY,
    ts REAL NOT NULL,
    found INTEGER NOT NULL DEFAULT 0
);

-- Shadow data (nothing reads it to decide what a card shows): what each MAC looked like, and what a card carried over
-- when another MAC started answering at the same address. Only for analysis, see export/mac_shadow.py.
CREATE TABLE IF NOT EXISTS mac_memory (
    mac TEXT PRIMARY KEY,
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    device_id TEXT,
    ip TEXT,
    name TEXT,
    brand TEXT,
    grp TEXT,
    mobile_score INTEGER,
    dhcp_name TEXT,
    dhcp_class TEXT,
    hits INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS mac_takeover (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    device_id TEXT NOT NULL,
    ip TEXT,
    old_mac TEXT,
    new_mac TEXT,
    carried_name TEXT,
    carried_brand TEXT,
    carried_grp TEXT,
    old_dhcp_class TEXT,
    new_dhcp_class TEXT,
    old_dhcp_name TEXT,
    new_dhcp_name TEXT,
    new_known INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mac_takeover_ts ON mac_takeover (ts);
"""


class History(MacLayerMixin, ScansMixin, MacMemoryMixin, KnownMixin, PresenceMixin):
    """SQLite history: online/offline transitions, deep scans and
    a few service values. devices.yaml remains the configuration chosen
    by the user; only what the program observes over time goes here.

    All the methods are synchronous and protected by a lock: from the asyncio loop they
    are called with asyncio.to_thread, so a slow disk (e.g. during a
    host backup) does not block the page updates."""

    def __init__(self, path: Path = DB_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=NORMAL")
            self._db.executescript(_SCHEMA + _MACLAYER_SCHEMA)
            self._maclayer_migrate()
            self._db.commit()

    # ---- service values ----
    def meta_get(self, key: str) -> str | None:
        with self._lock:
            row = self._db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def meta_set(self, key: str, value: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            self._db.commit()

    def device_focus(self, device_id: str, since: float, limit: int = 400) -> dict:
        """Everything the database knows about one card in the period, for the "device under examination" section of the
        export: presence events (newest first, with the MAC seen), the times of the deep searches, the MAC changes behind
        the card and what each MAC of the card looked like."""
        def rows(sql, *args):
            return [dict(r) for r in self._db.execute(sql, args).fetchall()]
        with self._lock:
            out = {
                "presence": rows("SELECT ts, online, ip, mac FROM presence_events WHERE device_id = ? AND ts >= ? ORDER BY ts DESC LIMIT ?", device_id, since, limit),
                "scans": [r["ts"] for r in rows("SELECT ts FROM scans WHERE device_id = ? AND ts >= ? ORDER BY ts DESC LIMIT 60", device_id, since)],
            }
            try:
                out["mac_changes"] = rows("SELECT ts, ip, old_mac, new_mac, carried_name, carried_brand, carried_grp, new_known FROM mac_takeover WHERE device_id = ? AND ts >= ? ORDER BY ts DESC LIMIT 100", device_id, since)
                out["macs"] = rows("SELECT mac, first_seen, last_seen, name, brand, grp, mobile_score, dhcp_name, dhcp_class, hits FROM mac_memory WHERE device_id = ?", device_id)
            except sqlite3.OperationalError:
                out["mac_changes"], out["macs"] = [], []
        return out

    # ---- maintenance ----
    def prune(self) -> int:
        cutoff = time.time() - PRESENCE_RETENTION_DAYS * 86400
        with self._lock:
            # For each device the latest event is always kept even if
            # old: it is needed to know what state the window starts in.
            cur = self._db.execute(
                """DELETE FROM presence_events WHERE ts < ? AND id NOT IN
                   (SELECT MAX(id) FROM presence_events GROUP BY device_id)""",
                (cutoff,),
            )
            # Latency: only the last 7 days (one sample per minute per device).
            self._db.execute("DELETE FROM latency WHERE ts < ?", (time.time() - LATENCY_RETENTION_DAYS * 86400,))
            self._db.execute("DELETE FROM mac_memory WHERE last_seen < ?", (time.time() - SHADOW_RETENTION_DAYS * 86400,))
            self._db.execute("DELETE FROM mac_takeover WHERE ts < ?", (time.time() - SHADOW_RETENTION_DAYS * 86400,))
            self._db.commit()
            removed = cur.rowcount
        self.prune_maclayer()
        return removed


history = History()
