import json
import sqlite3
import threading
import time
from pathlib import Path

from .paths import DATA_DIR as CONFIG_DIR
DB_PATH = CONFIG_DIR / "vedetta.db"

PRESENCE_RETENTION_DAYS = 90
SCANS_KEPT_PER_DEVICE = 30
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

-- Shadow data (nothing reads it to decide what a card shows): what each MAC looked like, and what a card carried over
-- when another MAC started answering at the same address. Only for analysis, see mac_shadow.py.
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


class History:
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
            self._db.executescript(_SCHEMA)
            self._db.commit()

    # ---- presence ----
    def record_presence(self, device_id: str, ip: str | None, mac: str | None, online: bool, ts: float) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO presence_events (device_id, ip, mac, online, ts) VALUES (?, ?, ?, ?, ?)",
                (device_id, ip, mac, int(online), ts),
            )
            self._db.commit()

    def last_presence(self) -> dict[str, tuple[bool, float]]:
        """Latest known event of each device: {id: (online, ts)}."""
        with self._lock:
            rows = self._db.execute(
                """SELECT device_id, online, ts FROM presence_events
                   WHERE id IN (SELECT MAX(id) FROM presence_events GROUP BY device_id)"""
            ).fetchall()
        return {r["device_id"]: (bool(r["online"]), r["ts"]) for r in rows}

    def presence_flaps(self, since: float) -> dict[str, int]:
        """Number of online/offline transitions per device after `since`.
        Phones and laptops have many (they join and leave the network), fixed
        equipment almost none: the "mobile" hint of identity.py."""
        with self._lock:
            rows = self._db.execute(
                "SELECT device_id, COUNT(*) AS n FROM presence_events WHERE ts >= ? GROUP BY device_id",
                (since,),
            ).fetchall()
        return {r["device_id"]: r["n"] for r in rows}

    def private_mac_counts(self, since: float) -> dict[str, int]:
        """Distinct private (randomized, "locally administered") MACs seen per device after `since`. A phone that
        rotates its Wi-Fi address has several; a MAC seen under more than one device (a repeater lending its own
        address to the clients behind it) says nothing about any of them and is ignored."""
        with self._lock:
            rows = self._db.execute(
                "SELECT DISTINCT device_id, mac FROM presence_events WHERE mac IS NOT NULL AND ts >= ?", (since,)).fetchall()
        owners: dict[str, set] = {}
        for r in rows:
            owners.setdefault(r["mac"].lower(), set()).add(r["device_id"])
        counts: dict[str, int] = {}
        for mac, devices in owners.items():
            try:
                private = bool(int(mac[:2], 16) & 2)
            except ValueError:
                continue
            if private and len(devices) == 1:
                device = next(iter(devices))
                counts[device] = counts.get(device, 0) + 1
        return counts

    def first_presence(self, device_ids: list[str]) -> dict[str, float]:
        """When each card was first seen."""
        if not device_ids:
            return {}
        marks = ",".join("?" * len(device_ids))
        with self._lock:
            rows = self._db.execute(
                f"SELECT device_id, MIN(ts) AS ts FROM presence_events WHERE device_id IN ({marks}) GROUP BY device_id", device_ids).fetchall()
        return {r["device_id"]: r["ts"] for r in rows}

    def online_overlap(self, a: str, b: str, since: float, until: float) -> float:
        """Seconds in which both devices were online at the same time in the window."""
        segs = [[(s["from"], s["to"]) for s in self.presence_segments(d, since, until)["segments"] if s["online"]] for d in (a, b)]
        return sum(max(0.0, min(x1, y1) - max(x0, y0)) for x0, x1 in segs[0] for y0, y1 in segs[1])

    def reassign_device(self, source: str, target: str) -> None:
        """The history of a card that is merged into another one goes with it (presence, scans, latency)."""
        with self._lock:
            for table in ("presence_events", "scans", "latency"):
                self._db.execute(f"UPDATE {table} SET device_id = ? WHERE device_id = ?", (target, source))
            self._db.commit()

    def presence_segments(self, device_id: str, since: float, until: float) -> dict:
        """Online/offline segments of the device in the window [since, until].
        Before the first known event the state is unknown: no segment,
        so the chart shows it as "no data" and not as offline."""
        with self._lock:
            before = self._db.execute(
                "SELECT online FROM presence_events WHERE device_id = ? AND ts <= ? ORDER BY ts DESC, id DESC LIMIT 1",
                (device_id, since),
            ).fetchone()
            events = self._db.execute(
                "SELECT online, ts FROM presence_events WHERE device_id = ? AND ts > ? AND ts <= ? ORDER BY ts, id",
                (device_id, since, until),
            ).fetchall()

        segments: list[dict] = []
        state = bool(before["online"]) if before else None
        cursor = since
        for ev in events:
            if state is not None and ev["ts"] > cursor:
                segments.append({"from": cursor, "to": ev["ts"], "online": state})
            state, cursor = bool(ev["online"]), ev["ts"]
        if state is not None and until > cursor:
            segments.append({"from": cursor, "to": until, "online": state})

        known = sum(s["to"] - s["from"] for s in segments)
        online = sum(s["to"] - s["from"] for s in segments if s["online"])
        return {
            "from": since,
            "to": until,
            "segments": segments,
            "online_pct": round(100 * online / known, 1) if known > 0 else None,
        }

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

    def last_mac(self, device_id: str) -> str | None:
        """Latest known MAC of a device (used to wake it up when it is
        off and the probe no longer sees its MAC)."""
        with self._lock:
            row = self._db.execute(
                "SELECT mac FROM presence_events WHERE device_id = ? AND mac IS NOT NULL ORDER BY id DESC LIMIT 1",
                (device_id,),
            ).fetchone()
        return row["mac"] if row else None

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

    def known_ignore(self, macs: list[str] | None) -> None:
        """'new' -> 'ignored' for the given MACs, or for all of them if macs is None."""
        with self._lock:
            if macs is None:
                self._db.execute("UPDATE known_macs SET status = 'ignored' WHERE status = 'new'")
            else:
                self._db.executemany("UPDATE known_macs SET status = 'ignored' WHERE status = 'new' AND mac = ?",
                                     [(m,) for m in macs])
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

    # ---- shadow data per MAC (analysis only) ----
    def mac_memory_set(self, mac: str, device_id: str, ip: str | None, fields: dict, ts: float) -> None:
        with self._lock:
            self._db.execute(
                """INSERT INTO mac_memory (mac, first_seen, last_seen, device_id, ip, name, brand, grp, mobile_score, dhcp_name, dhcp_class)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(mac) DO UPDATE SET last_seen = excluded.last_seen, device_id = excluded.device_id, ip = excluded.ip,
                       name = excluded.name, brand = excluded.brand, grp = excluded.grp, mobile_score = excluded.mobile_score,
                       dhcp_name = excluded.dhcp_name, dhcp_class = excluded.dhcp_class, hits = hits + 1""",
                (mac, ts, ts, device_id, ip, fields.get("name"), fields.get("brand"), fields.get("grp"), fields.get("mobile_score"),
                 fields.get("dhcp_name"), fields.get("dhcp_class")))
            self._db.commit()

    def mac_known(self, mac: str) -> bool:
        with self._lock:
            return self._db.execute("SELECT 1 FROM mac_memory WHERE mac = ?", (mac,)).fetchone() is not None

    def mac_takeover_add(self, ts: float, device_id: str, ip: str | None, old_mac: str, new_mac: str, carried: dict,
                         old_dhcp: dict, new_dhcp: dict, new_known: bool) -> None:
        with self._lock:
            self._db.execute(
                """INSERT INTO mac_takeover (ts, device_id, ip, old_mac, new_mac, carried_name, carried_brand, carried_grp,
                       old_dhcp_class, new_dhcp_class, old_dhcp_name, new_dhcp_name, new_known) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (ts, device_id, ip, old_mac, new_mac, carried.get("name"), carried.get("brand"), carried.get("grp"),
                 old_dhcp.get("vendor_class"), new_dhcp.get("vendor_class"), old_dhcp.get("hostname"), new_dhcp.get("hostname"),
                 int(new_known)))
            self._db.commit()

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
            return cur.rowcount


history = History()
