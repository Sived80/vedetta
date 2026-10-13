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
        for table in ("scans", "latency", "mac_takeover"):
            run(f"DELETE FROM {table} WHERE ts < ? OR ts > ?", since, until)
        run("DELETE FROM mac_memory WHERE last_seen < ? OR first_seen > ?", since, until)
        con.commit()
        con.execute("VACUUM")
    finally:
        con.close()


# ------------------------------------------------------------------ how big it will be
_est_cache: dict = {"key": None, "data": None, "at": 0.0}


def estimate() -> dict:
    """Bytes of raw data for each of the last HORIZON_DAYS days (index 0 = today), what is always in the file, and the limit:
    the window uses them to say how big a period will be and to draw the columns."""
    _result, data_dir, key, daily, base, mid, add_, db_path, log_path = _open_estimate_buckets()
    if _result is not None:
        return _result
    ts = _add_database_row_sizes(db_path, add_, mid)
    base = _add_log_and_data_file_sizes(log_path, base, data_dir, ts, add_)
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


def _add_database_row_sizes(db_path, add_, mid):
    ts = None            # set below on some paths only
    if not db_path.exists():
        return ts
    since = (mid - HORIZON_DAYS * 86400,)
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        for table, size in (("presence_events", 90), ("latency", 40), ("mac_takeover", 250)):
            for (ts,) in _rows(con, f"SELECT ts FROM {table} WHERE ts >= ?", since):
                add_(ts, size)
        for ts, n in _rows(con, "SELECT ts, length(result_json) FROM scans WHERE ts >= ?", since):
            add_(ts, int(n or 0) + 40)
        con.close()
    except sqlite3.Error:
        pass
    return ts


def _rows(con, sql, params):
    """The rows of a query; a table that is not there (an older database) has none."""
    try:
        yield from con.execute(sql, params)
    except sqlite3.OperationalError:
        return


def _add_log_and_data_file_sizes(log_path, base, data_dir, ts, add_):
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
