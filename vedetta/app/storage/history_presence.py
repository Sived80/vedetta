"""PresenceMixin: methods of History that belong together (moved out of history.py by tools/split_class.py)."""
import time
from itertools import product

from . import overlap


def _is_private(mac: str) -> bool:
    """The locally administered bit: the address was made up by the device, not assigned by a manufacturer."""
    try:
        return bool(int(mac[:2], 16) & 2)
    except ValueError:
        return False


class PresenceMixin:
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

    def private_mac_counts(self, since: float, now: float | None = None) -> dict[str, int]:
        """Distinct private (randomized, "locally administered") MACs seen per device after `since`. A phone that rotates its Wi-Fi address has
        several. A MAC that several cards used at the same time (a repeater lending its own address to the clients behind it, see storage/overlap.py)
        says nothing about any of them and is ignored; one phone seen on two cards one after the other keeps its MAC on both."""
        with self._lock:
            rows = self._db.execute("SELECT device_id, mac, online, ts FROM presence_events WHERE ts >= ? ORDER BY ts, id", (since,)).fetchall()
        lent = overlap.shared_macs([(r["device_id"], (r["mac"] or "").lower() or None, r["online"], r["ts"]) for r in rows], time.time() if now is None else now)
        counts: dict[str, int] = {}
        for device, mac in {(r["device_id"], r["mac"].lower()) for r in rows if r["mac"]}:
            if _is_private(mac) and mac not in lent:
                counts[device] = counts.get(device, 0) + 1
        return counts

    def first_event_ts(self) -> float | None:
        """When the very first presence event was written (how long this installation has been watching), or None."""
        with self._lock:
            row = self._db.execute("SELECT MIN(ts) AS ts FROM presence_events").fetchone()
        return row["ts"] if row else None

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
        return sum(max(0.0, min(x1, y1) - max(x0, y0)) for (x0, x1), (y0, y1) in product(segs[0], segs[1]))

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
        before, events = self._presence_window(device_id, since, until)
        segments = _segments_from_events(before, events, since, until)
        return _segments_report(segments, since, until)

    def _presence_window(self, device_id: str, since: float, until: float):
        """The last event at or before `since` (or None) and the events inside (since, until], oldest first."""
        with self._lock:
            before = self._db.execute(
                "SELECT online FROM presence_events WHERE device_id = ? AND ts <= ? ORDER BY ts DESC, id DESC LIMIT 1",
                (device_id, since),
            ).fetchone()
            events = self._db.execute(
                "SELECT online, ts FROM presence_events WHERE device_id = ? AND ts > ? AND ts <= ? ORDER BY ts, id",
                (device_id, since, until),
            ).fetchall()
        return before, events


def _segments_from_events(before, events, since: float, until: float) -> list[dict]:
    """Walks the events: each known state lasts until the next event (the last one until `until`); an unknown state makes no segment."""
    segments: list[dict] = []
    state = bool(before["online"]) if before else None
    cursor = since
    for ev in events:
        if state is not None and ev["ts"] > cursor:
            segments.append({"from": cursor, "to": ev["ts"], "online": state})
        state, cursor = bool(ev["online"]), ev["ts"]
    if state is not None and until > cursor:
        segments.append({"from": cursor, "to": until, "online": state})
    return segments


def _segments_report(segments: list[dict], since: float, until: float) -> dict:
    """The answer of presence_segments: the window, the segments and the percentage of the known time spent online."""
    known = sum(s["to"] - s["from"] for s in segments)
    online = sum(s["to"] - s["from"] for s in segments if s["online"])
    return {
        "from": since,
        "to": until,
        "segments": segments,
        "online_pct": round(100 * online / known, 1) if known > 0 else None,
    }
