# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""export_estimate: moved out of export_engine.py (see tools/split_module.py)."""
from pathlib import Path
from datetime import datetime, timedelta
from ..storage import devices_config
from ..ha import ha_tz
import json
from .. import paths
import re
import sqlite3
from ..state import state
import threading
import time


HORIZON_DAYS = 90                    # how far back the history goes (the retention of the presence events)


LIMIT_BYTES = 20 * 1024 * 1024       # the file for the developer


MAX_LOG_PERIOD = 12 * 1024 * 1024    # the log of the period, newest lines kept above this


ZIP_RATIO = 0.3                      # estimates only: how much the zip is of the raw data


SEAL_FACTOR = 1.34                   # base64 of the sealed zip


# ------------------------------------------------------------------ the period
def day_start(days_ago: int) -> float:
    """Local midnight (Home Assistant time) of the day `days_ago` days ago."""
    d = ha_tz.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=int(days_ago))
    return d.timestamp()


def bounds(first_day: int | None, last_day: int | None) -> tuple[float | None, float | None]:
    """(since, until) of the days chosen: first_day = the oldest included (days ago), last_day = the newest (0 = today, until now)."""
    if first_day is None:
        return None, None
    since = day_start(first_day)
    until = time.time() if not last_day else day_start(int(last_day) - 1)
    return since, until


_TS = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)?)")


def _line_ts(line: str) -> float | None:
    m = _TS.match(line)
    if not m:
        return None
    try:
        return datetime.fromisoformat(m.group(1).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def filter_log(text: str, since: float, until: float, cap: int = MAX_LOG_PERIOD) -> str:
    """The lines of the period (a line without a time, like a traceback row, goes with the line before it)."""
    keep, ok = [], True
    for line in text.split(chr(10)):
        ts = _line_ts(line)
        if ts is not None:
            ok = since <= ts <= until
        if ok:
            keep.append(line)
    size = 0
    for i in range(len(keep) - 1, -1, -1):                       # too much: the newest lines are the ones that matter
        size += len(keep[i].encode("utf-8", "replace")) + 1
        if size > cap:
            keep = keep[i + 1:]
            break
    return chr(10).join(keep)


def filter_jsonl(text: str, since: float, until: float) -> str:
    out = []
    for line in text.split(chr(10)):
        if not line.strip():
            continue
        try:
            ts = json.loads(line).get("ts")
        except (ValueError, AttributeError):
            out.append(line)
            continue
        if not isinstance(ts, (int, float)) or since <= ts <= until:
            out.append(line)
    return chr(10).join(out)


def _period_db(path: Path, since: float, until: float) -> None:
    """Keeps in the copy of the database only the period (and, for the presence, the last event before it: it says what the
    state was when the period began)."""
    con = sqlite3.connect(path)
    try:
        def run(sql, *args):
            try:
                con.execute(sql, args)
            except sqlite3.OperationalError:
                pass                                              # a table an older database does not have
        run("DELETE FROM presence_events WHERE ts > ? OR (ts < ? AND id NOT IN (SELECT MAX(id) FROM presence_events WHERE ts < ? GROUP BY device_id))", until, since, since)
        for table in ("scans", "latency", "mac_takeover", "identity_change"):
            run(f"DELETE FROM {table} WHERE ts < ? OR ts > ?", since, until)  # noqa: S608  table names from a fixed tuple
        run("DELETE FROM mac_memory WHERE last_seen < ? OR first_seen > ?", since, until)
        run("DELETE FROM routed_seen WHERE last_seen < ? OR first_seen > ?", since, until)      # 1.0: the addresses behind the router seen in the period
        con.commit()
        con.execute("VACUUM")
    finally:
        con.close()


# ------------------------------------------------------------------ how big it will be
_est_cache: dict = {"key": None, "data": None, "at": 0.0}
_est_lock = threading.Lock()


def estimate() -> dict:
    """Bytes of raw data for each of the last HORIZON_DAYS days (index 0 = today), what is always in the file, and the limit:
    the window uses them to say how big a period will be and to draw the columns. One computation at a time: a request that
    waited for another takes its result (the page asks again when it gets no answer, and each ask used to start it anew)."""
    asked = time.time()
    with _est_lock:
        if _est_cache["data"] is not None and _est_cache["at"] >= asked:
            return _est_cache["data"]
        return _estimate()


def _estimate() -> dict:
    _result, data_dir, key, daily, base, mid, add_, db_path, log_path = _open_estimate_buckets()
    if _result is not None:
        return _result
    _add_database_row_sizes(db_path, add_, mid)
    base = _add_log_and_data_file_sizes(log_path, base, data_dir, add_)
    return _cache_estimate_result(daily, base, key)


def _open_estimate_buckets():
    data_dir = paths.DATA_DIR
    db_path, log_path = data_dir / "vedetta.db", data_dir / "dashboard.log"
    key = (db_path.stat().st_mtime if db_path.exists() else 0, log_path.stat().st_mtime if log_path.exists() else 0, len(state.devices))
    if _est_cache["key"] == key and time.time() - _est_cache["at"] < 120:
        return (_est_cache["data"]), None, None, None, None, None, None, None, None
    daily = [0] * HORIZON_DAYS
    base = 25 * 1024 * len(state.devices) + 60 * 1024
    mid = day_start(0)

    def add(ts: float, nbytes: int) -> None:
        age = int((mid + 86400 - ts) // 86400)                    # 0 = today
        if 0 <= age < HORIZON_DAYS:
            daily[age] += nbytes
    add_ = add
    return None, data_dir, key, daily, base, mid, add_, db_path, log_path


# the day of a row (0 = today) and its bytes, counted by the database: a history of weeks has millions of ping samples, and reading
# them one by one took longer than the page waits
_AGE = "CAST((? - ts) / 86400.0 AS INTEGER)"
_DAY_SIZES = [f"SELECT {_AGE}, COUNT(*) * {size} FROM {table} WHERE ts >= ? AND ts < ? GROUP BY 1"  # noqa: S608  fixed names
              for table, size in (("presence_events", 90), ("latency", 40), ("mac_takeover", 250))]
_DAY_SIZES.append("SELECT CAST((? - ts) / 86400.0 AS INTEGER), SUM(COALESCE(length(result_json), 0) + 40) FROM scans WHERE ts >= ? AND ts < ? GROUP BY 1")


def _add_database_row_sizes(db_path, add_, mid):
    """Adds each day's bytes of the database rows (through add_, at the middle of that day)."""
    if not db_path.exists():
        return None
    end = float(mid + 86400)
    for age, nbytes in _day_sizes(db_path, (end, mid - HORIZON_DAYS * 86400, end)):
        add_(end - (int(age) + 0.5) * 86400, int(nbytes or 0))
    return None


def _day_sizes(db_path, params) -> list:
    """[(day, bytes)] of every table, read-only; [] when the database cannot be read."""
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    try:
        return [row for sql in _DAY_SIZES for row in _rows(con, sql, params)]
    except sqlite3.Error:
        return []
    finally:
        con.close()


def _rows(con, sql, params):
    """The rows of a query; a table that is not there (an older database) has none."""
    try:
        yield from con.execute(sql, params)
    except sqlite3.OperationalError:
        return


def _add_log_and_data_file_sizes(log_path, base, data_dir, add_):
    _add_log_line_sizes(log_path, add_)
    return base + _settings_files_size(data_dir)


def _add_log_line_sizes(log_path, add_) -> None:
    """Each line of the log that begins with a time is counted at its day: its length plus the line end. A log that is not there or cannot be read adds nothing."""
    if not log_path.exists():
        return
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").split(chr(10))
    except OSError:
        return
    for line in lines:
        line_ts = _line_ts(line)
        if line_ts is not None:
            add_(line_ts, len(line) + 1)


def _settings_files_size(data_dir) -> int:
    """The size of the settings files (.json and .yaml, not the database) of the data folder."""
    if not data_dir.exists():
        return 0
    return sum(f.stat().st_size for f in data_dir.iterdir() if f.is_file() and f.suffix in (".json", ".yaml") and not f.name.startswith("vedetta.db"))


def _cache_estimate_result(daily, base, key) -> dict:
    out = {"daily": daily, "base": base, "ratio": ZIP_RATIO, "seal_factor": SEAL_FACTOR, "limit": LIMIT_BYTES, "horizon": HORIZON_DAYS,
           "flagged": sum(1 for c in devices_config.load_devices() if c.get("focus"))}
    _est_cache.update(key=key, data=out, at=time.time())
    return out
