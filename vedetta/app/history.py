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
"""


class History:
    """Storico su SQLite: transizioni online/offline, scansioni approfondite e
    qualche valore di servizio. devices.yaml resta la configurazione scelta
    dall'utente; qui va solo cio' che il programma osserva nel tempo.

    Tutti i metodi sono sincroni e protetti da un lock: dal loop asyncio si
    chiamano con asyncio.to_thread, cosi' un disco lento (es. durante un
    backup dell'host) non blocca l'aggiornamento delle pagine."""

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

    # ---- presenza ----
    def record_presence(self, device_id: str, ip: str | None, mac: str | None, online: bool, ts: float) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO presence_events (device_id, ip, mac, online, ts) VALUES (?, ?, ?, ?, ?)",
                (device_id, ip, mac, int(online), ts),
            )
            self._db.commit()

    def last_presence(self) -> dict[str, tuple[bool, float]]:
        """Ultimo evento noto di ogni dispositivo: {id: (online, ts)}."""
        with self._lock:
            rows = self._db.execute(
                """SELECT device_id, online, ts FROM presence_events
                   WHERE id IN (SELECT MAX(id) FROM presence_events GROUP BY device_id)"""
            ).fetchall()
        return {r["device_id"]: (bool(r["online"]), r["ts"]) for r in rows}

    def presence_flaps(self, since: float) -> dict[str, int]:
        """Numero di transizioni online/offline per dispositivo dopo `since`.
        Telefoni e portatili ne fanno molte (entrano e escono dalla rete), le
        apparecchiature fisse quasi nessuna: indizio "mobile" di identity.py."""
        with self._lock:
            rows = self._db.execute(
                "SELECT device_id, COUNT(*) AS n FROM presence_events WHERE ts >= ? GROUP BY device_id",
                (since,),
            ).fetchall()
        return {r["device_id"]: r["n"] for r in rows}

    def presence_segments(self, device_id: str, since: float, until: float) -> dict:
        """Segmenti online/offline del dispositivo nella finestra [since, until].
        Prima del primo evento noto lo stato e' sconosciuto: nessun segmento,
        cosi' il grafico lo mostra come "nessun dato" e non come offline."""
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

    # ---- scansioni ----
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
        """Ultimo MAC noto di un dispositivo (serve a svegliarlo quando e'
        spento e il probe non ne vede piu' il MAC)."""
        with self._lock:
            row = self._db.execute(
                "SELECT mac FROM presence_events WHERE device_id = ? AND mac IS NOT NULL ORDER BY id DESC LIMIT 1",
                (device_id,),
            ).fetchone()
        return row["mac"] if row else None

    # ---- MAC noti (nuovi dispositivi in rete) ----
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
        """'new' -> 'ignored' per i MAC dati, o per tutti se macs e' None."""
        with self._lock:
            if macs is None:
                self._db.execute("UPDATE known_macs SET status = 'ignored' WHERE status = 'new'")
            else:
                self._db.executemany("UPDATE known_macs SET status = 'ignored' WHERE status = 'new' AND mac = ?",
                                     [(m,) for m in macs])
            self._db.commit()

    # ---- tempo di risposta ----
    def record_latency(self, rows: list[tuple[str, float, float]]) -> None:
        """Campioni (device_id, ts, ms), tutti in una sola transazione."""
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

    # ---- valori di servizio ----
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

    # ---- manutenzione ----
    def prune(self) -> int:
        cutoff = time.time() - PRESENCE_RETENTION_DAYS * 86400
        with self._lock:
            # Di ogni dispositivo si tiene sempre l'ultimo evento anche se
            # vecchio: serve a sapere in che stato si trova la finestra.
            cur = self._db.execute(
                """DELETE FROM presence_events WHERE ts < ? AND id NOT IN
                   (SELECT MAX(id) FROM presence_events GROUP BY device_id)""",
                (cutoff,),
            )
            # Latenza: solo gli ultimi 7 giorni (un campione al minuto per dispositivo).
            self._db.execute("DELETE FROM latency WHERE ts < ?", (time.time() - LATENCY_RETENTION_DAYS * 86400,))
            self._db.commit()
            return cur.rowcount


history = History()
