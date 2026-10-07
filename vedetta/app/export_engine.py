"""The export for analysis, in two phases and for two readers.

  dest "dev": for the author of Vedetta (a report attached to a public issue). IPs, MACs, names and emails are masked, the
              result is checked, what is still readable is replaced (the "fix" step) and what cannot be replaced is shown to
              the person, who removes it or keeps it. The caller seals the zip (report_crypto).
  dest "me" : for the person themselves. Nothing is masked and nothing is checked: it is their own data. Only the fields
              that look like a credential are still replaced (a file handed over by mistake must not carry a password).

The period (first_day..last_day, in days ago, 0 = today) limits the history: the database rows, the log and the journal. The
files that describe the situation now (devices, evidence, registry) are always complete.

prepare() does the slow part and returns what is left to decide; finish() applies the choices and writes the zip."""
import io
import json
import platform
import re
import shutil
import sqlite3
import tempfile
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from . import anonymize, devices_config, dhcp, evidence, ha_registry, ha_tz, journal, maintenance, mdns_listener, mqtt_ha, paths, roles, settings
from . import export as legacy
from .state import state

HORIZON_DAYS = 90                    # how far back the history goes (the retention of the presence events)
LIMIT_BYTES = 20 * 1024 * 1024       # the file for the developer
MAX_LOG_PERIOD = 12 * 1024 * 1024    # the log of the period, newest lines kept above this
JOURNAL_LIMIT = 2000
REMOVED = "[removed]"
FORMAT = 2                           # 1 = the old export (lines removed, no period, no destination); 2 = this one
ZIP_RATIO = 0.3                      # estimates only: how much the zip is of the raw data
SEAL_FACTOR = 1.34                   # base64 of the sealed zip
STEPS_DEV = ("collect", "mask", "check", "fix", "seal", "ready")
FOCUS_DEFAULT_DAYS = legacy.FOCUS_DAYS


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
    data_dir = paths.DATA_DIR
    db_path, log_path = data_dir / "vedetta.db", data_dir / "dashboard.log"
    key = (db_path.stat().st_mtime if db_path.exists() else 0, log_path.stat().st_mtime if log_path.exists() else 0, len(state.devices))
    if _est_cache["key"] == key and time.time() - _est_cache["at"] < 120:
        return _est_cache["data"]
    daily = [0] * HORIZON_DAYS
    base = 25 * 1024 * len(state.devices) + 60 * 1024
    mid = day_start(0)

    def add(ts: float, nbytes: int) -> None:
        age = int((mid + 86400 - ts) // 86400)                    # 0 = today
        if 0 <= age < HORIZON_DAYS:
            daily[age] += nbytes
    if db_path.exists():
        try:
            con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            for table, size in (("presence_events", 90), ("latency", 40), ("mac_takeover", 250)):
                try:
                    for (ts,) in con.execute(f"SELECT ts FROM {table} WHERE ts >= ?", (mid - HORIZON_DAYS * 86400,)):
                        add(ts, size)
                except sqlite3.OperationalError:
                    pass
            try:
                for ts, n in con.execute("SELECT ts, length(result_json) FROM scans WHERE ts >= ?", (mid - HORIZON_DAYS * 86400,)):
                    add(ts, int(n or 0) + 40)
            except sqlite3.OperationalError:
                pass
            con.close()
        except sqlite3.Error:
            pass
    if log_path.exists():
        try:
            for line in log_path.read_text(encoding="utf-8", errors="replace").split(chr(10)):
                ts = _line_ts(line)
                if ts is not None:
                    add(ts, len(line) + 1)
        except OSError:
            pass
    for f in (data_dir.iterdir() if data_dir.exists() else []):
        if f.is_file() and f.suffix in (".json", ".yaml") and not f.name.startswith("vedetta.db"):
            base += f.stat().st_size
    out = {"daily": daily, "base": base, "ratio": ZIP_RATIO, "seal_factor": SEAL_FACTOR, "limit": LIMIT_BYTES, "horizon": HORIZON_DAYS,
           "flagged": sum(1 for c in devices_config.load_devices() if c.get("focus"))}
    _est_cache.update(key=key, data=out, at=time.time())
    return out


# ------------------------------------------------------------------ phase 1
class Prepared:
    def __init__(self, dest: str) -> None:
        self.dest = dest
        self.files: dict[str, list] = {}          # name -> ["text", str] or ["db", Path]
        self.pending: list[dict] = []             # what is still readable and could not be replaced: the person decides
        self.fixed = 0
        self.manifest: dict = {}
        self.anon: anonymize.Anonymizer | None = None
        self.tmp = tempfile.TemporaryDirectory(prefix="vedetta-export-")

    def close(self) -> None:
        try:
            self.tmp.cleanup()
        except OSError:
            pass


def _text_of(path: Path) -> str | None:
    try:
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _gather(p: Prepared, since: float | None, until: float | None) -> None:
    """The raw files (nothing masked yet)."""
    from .routes_ha import device_debug
    from . import ha_data
    data_dir = paths.DATA_DIR
    m = p.manifest
    m.update({"omitted": [], "lines_removed": [], "created": time.strftime("%Y-%m-%d %H:%M:%S"), "version": mqtt_ha.version(),
              "python": platform.python_version(), "platform": platform.platform(), "files": {}, "notes": [], "dest": p.dest, "format": FORMAT})
    try:
        pending = sum(1 for d in devices_config.load_devices() if not maintenance.last_deep_attempt(d))
    except Exception:
        pending = None
    m["time"] = {"utc_offset": ha_tz.now().strftime("%z"), "from_home_assistant": ha_tz._state["zone"] is not None, "night_hour": maintenance.NIGHT_HOUR}
    m["deep_search"] = {"never_analysed": pending, "devices": len(state.devices)}
    m["phone_merge"] = state.merge_report
    m["period"] = {"from": since, "until": until, "all": since is None}
    add = lambda name, text: p.files.__setitem__(name, ["text", text])                      # noqa: E731
    if data_dir.exists():
        for f in sorted(data_dir.iterdir()):
            if not f.is_file() or f.name.startswith("vedetta.db") or f.name == legacy.MAPPING_FILE or any(w in f.name.lower() for w in legacy.SKIP_WORDS):
                continue
            try:
                text = _text_of(f) if f.suffix not in (".log", ".jsonl") or since is not None else legacy._tail(f, legacy.MAX_LOG_BYTES).decode("utf-8", "replace")
                if text is None:
                    m["notes"].append(f"{f.name}: binary file not included")
                    continue
                if f.suffix == ".json":
                    text = json.dumps(legacy._redact(json.loads(text)), ensure_ascii=False, indent=1)
                elif f.suffix == ".log" and since is not None:
                    text = filter_log(text, since, until)
                elif f.suffix == ".jsonl" and since is not None:
                    text = filter_jsonl(text, since, until)
                add(f"data/{f.name}", text)
            except Exception as exc:               # an unreadable file must not stop the export
                m["notes"].append(f"{f.name}: {exc!r}")
    db = data_dir / "vedetta.db"
    if db.exists():
        if db.stat().st_size > legacy.MAX_DB_BYTES and since is None:
            m["notes"].append(f"vedetta.db not included ({db.stat().st_size} bytes)")
        else:
            try:
                copy = Path(p.tmp.name) / "vedetta.db"
                src = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
                dst = sqlite3.connect(copy)
                src.backup(dst)
                dst.close()
                src.close()
                if since is not None:
                    _period_db(copy, since, until)
                p.files["data/vedetta.db"] = ["db", copy]
            except Exception as exc:
                m["notes"].append(f"vedetta.db: {exc!r}")
    dbg, evi = {}, {}
    for did in list(state.devices):
        try:
            debug = device_debug(did)
            dbg[did] = {"name": state.devices[did].get("name"), "ip": state.devices[did].get("ip"), "debug": debug}
            evi[did] = evidence.summarize(debug, state.devices[did])
        except Exception as exc:
            dbg[did] = {"error": repr(exc)}
    # the "device under examination" section
    try:
        from .history import history
        flagged = [c for c in devices_config.load_devices() if c.get("focus")][:devices_config.FOCUS_MAX]
        focus = {"days": FOCUS_DEFAULT_DAYS if since is None else max(1, round((until - since) / 86400)), "devices": []}
        h_since = since if since is not None else time.time() - FOCUS_DEFAULT_DAYS * 86400
        for cfg in flagged:
            did = cfg["id"]
            dev = state.devices.get(did)
            if not dev:
                continue
            card = ha_data.compact_device(dev, cfg)
            card.pop("focus_note", None)
            focus["devices"].append({"id": did, "name": dev.get("name"), "note": cfg.get("focus_note"), "card": card, "evidence": evi.get(did),
                                     "debug": (dbg.get(did) or {}).get("debug"), "history": history.device_focus(did, h_since)})
        m["focus"] = {"devices": len(focus["devices"]), "with_note": sum(1 for x in focus["devices"] if x["note"]), "days": focus["days"]}
        if focus["devices"]:
            add("state/focus.json", json.dumps(focus, ensure_ascii=False, indent=1, default=str))
    except Exception as exc:
        m["notes"].append(f"focus: {exc!r}")
    dump = lambda obj: json.dumps(obj, ensure_ascii=False, indent=1, default=str)             # noqa: E731
    add("state/devices_debug.json", dump(dbg))
    add("state/evidence.json", dump(evi))
    add("state/devices_compact.json", dump(ha_data.compact_all(state.sorted_devices())))
    add("state/ha_registry.json", dump({"status": ha_registry.status(), "by_mac": ha_registry._state["by_mac"], "by_ip": ha_registry._state["by_ip"]}))
    add("state/mdns_seen.json", dump({"by_mac": mdns_listener.by_mac, "by_ip": mdns_listener.by_ip}))
    add("state/roles.json", dump(roles.snapshot()))
    add("state/dhcp_seen.json", dump(dhcp.seen))
    add("state/settings.json", dump(legacy._redact(settings.load())))
    try:
        entries = journal.entries("detail", JOURNAL_LIMIT if since is not None else 500)
        if since is not None:
            entries = [e for e in entries if not isinstance(e.get("ts"), (int, float)) or since <= e["ts"] <= until]
        add("state/journal.json", dump(entries))
    except Exception as exc:
        m["notes"].append(f"journal: {exc!r}")


def _mask_text(name: str, text: str, anon: anonymize.Anonymizer) -> str:
    try:
        if name.endswith(".json"):
            return json.dumps(anon.data(json.loads(text)), ensure_ascii=False, indent=1)
        if name.endswith(".jsonl"):
            return chr(10).join(json.dumps(anon.data(json.loads(line)), ensure_ascii=False) if line.strip() else "" for line in text.split(chr(10)))
    except ValueError:
        pass
    return anon.text(text)


def _mask_db(path: Path, anon: anonymize.Anonymizer) -> None:
    con = sqlite3.connect(path)
    try:
        con.create_function("anon", 1, lambda v: anon.text(v) if isinstance(v, str) else v)
        for tb in [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]:
            for _, col, *_r in con.execute(f'PRAGMA table_info("{tb}")').fetchall():
                con.execute(f"UPDATE \"{tb}\" SET \"{col}\" = anon(\"{col}\") WHERE typeof(\"{col}\") = 'text'")
        con.commit()
        con.execute("VACUUM")
    finally:
        con.close()


def _db_flagged(path: Path, anon: anonymize.Anonymizer) -> list[tuple[str, str, str]]:
    out = []
    con = sqlite3.connect(path)
    try:
        for tb in [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]:
            for _, col, *_r in con.execute(f'PRAGMA table_info("{tb}")').fetchall():
                for (value,) in con.execute(f"SELECT DISTINCT \"{col}\" FROM \"{tb}\" WHERE typeof(\"{col}\") = 'text'"):
                    if anon.leaks(value):
                        out.append((tb, col, value))
    finally:
        con.close()
    return out


def _is_flagged(name: str, text: str, anon: anonymize.Anonymizer) -> bool:
    try:
        if name.endswith(".json"):
            return bool(anon.leaks_data(json.loads(text)))
        if name.endswith(".jsonl"):
            return any(anon.leaks_data(json.loads(line)) for line in text.split(chr(10)) if line.strip())
    except ValueError:
        pass
    return bool(anon.leaks(text))


def _line_of(text: str, value: str) -> int:
    for i, line in enumerate(text.split(chr(10)), 1):
        if value in line:
            return i
    return 0


def _repair_file(name: str, text: str, anon: anonymize.Anonymizer) -> tuple[str, int, list[tuple[str, str, str]]]:
    """(text, replaced, [(kind, value, where)]) for one text file."""
    try:
        if name.endswith(".json"):
            obj, n, left = anon.repair_data(json.loads(text))
            return json.dumps(obj, ensure_ascii=False, indent=1), n, left
        if name.endswith(".jsonl"):
            rows, total, left = [], 0, []
            for i, line in enumerate(text.split(chr(10)), 1):
                if not line.strip():
                    rows.append("")
                    continue
                obj, n, rest = anon.repair_data(json.loads(line))
                rows.append(json.dumps(obj, ensure_ascii=False))
                total += n
                left += [(k, v, f"line {i}{w}") for k, v, w in rest]
            return chr(10).join(rows), total, left
    except ValueError:
        pass
    out, n, rest = anon.repair(text)
    return out, n, [(k, v, f"line {_line_of(out, v)}") for k, v in rest]


def prepare(dest: str, first_day: int | None = None, last_day: int | None = None, progress=None) -> Prepared:
    """Phase 1: gathers, masks (for the developer), checks and fixes. progress(step) is told when each step starts."""
    note = progress or (lambda step: None)
    since, until = bounds(first_day, last_day)
    p = Prepared(dest)
    try:
        note("collect")
        _gather(p, since, until)
        if dest != "dev":
            p.manifest["notes"].append("not masked: the person's own data (credentials replaced)")
            return p
        note("mask")
        p.anon = anon = legacy._collect(state.sorted_devices())
        p.manifest["notes"].append("anonymised: IP addresses (same last number), MAC addresses (same manufacturer prefix), names (numbered labels)")
        for name, entry in p.files.items():
            if entry[0] == "text":
                entry[1] = _mask_text(name, entry[1], anon)
            else:
                _mask_db(entry[1], anon)
        note("check")
        flagged_text = [n for n, e in p.files.items() if e[0] == "text" and _is_flagged(n, e[1], anon)]
        flagged_db = {n: _db_flagged(e[1], anon) for n, e in p.files.items() if e[0] == "db"}
        flagged_db = {n: v for n, v in flagged_db.items() if v}
        if not flagged_text and not flagged_db:
            return p
        note("fix")
        seen: set = set()

        def pend(name, kind, value, where):
            if (name, kind, value) not in seen:
                seen.add((name, kind, value))
                p.pending.append({"id": len(p.pending), "file": name, "kind": kind, "value": value, "where": where})
        for name in flagged_text:
            text, n, left = _repair_file(name, p.files[name][1], anon)
            p.files[name][1] = text
            p.fixed += n
            for kind, value, where in left:
                pend(name, kind, value, where)
        for name, rows in flagged_db.items():
            con = sqlite3.connect(p.files[name][1])
            try:
                for tb, col, value in rows:
                    text, n, left = anon.repair(value)
                    if text != value:
                        con.execute(f'UPDATE "{tb}" SET "{col}" = ? WHERE "{col}" = ?', (text, value))
                        p.fixed += n
                    for kind, v in left:
                        pend(name, kind, v, f"{tb}.{col}")
                con.commit()
            finally:
                con.close()
        return p
    except Exception:
        p.close()
        raise


# ------------------------------------------------------------------ phase 2
def _remove(p: Prepared, item: dict) -> None:
    name, value = item["file"], item["value"]
    entry = p.files[name]
    if entry[0] == "db":
        tb, col = item["where"].split(".", 1)
        con = sqlite3.connect(entry[1])
        try:
            con.execute(f'UPDATE "{tb}" SET "{col}" = replace("{col}", ?, ?) WHERE instr("{col}", ?) > 0', (value, REMOVED, value))
            con.commit()
        finally:
            con.close()
        return
    needle = json.dumps(value, ensure_ascii=False)[1:-1] if name.endswith((".json", ".jsonl")) else value
    entry[1] = entry[1].replace(needle, REMOVED)


def finish(p: Prepared, choices: dict | None = None, default: str = "rm") -> bytes:
    """Phase 2: applies what the person chose for each pending value ("rm" = remove it, "keep" = leave it as it is) and writes
    the zip. A value with no choice gets `default`."""
    choices = choices or {}
    removed = kept = 0
    for item in p.pending:
        if str(choices.get(item["id"], choices.get(str(item["id"]), default))) == "keep":
            kept += 1
        else:
            _remove(p, item)
            removed += 1
    m = p.manifest
    if p.dest == "dev":
        m["check"] = {"fixed": p.fixed, "removed": removed, "kept": kept}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, (kind, content) in p.files.items():
            raw = Path(content).read_bytes() if kind == "db" else content.encode("utf-8")
            z.writestr(name, raw)
            m["files"][name] = len(raw)
        z.writestr("manifest.json", json.dumps(m, ensure_ascii=False, indent=1))
    if p.dest == "dev" and p.anon is not None:
        legacy._save_mapping(p.anon)
    return buf.getvalue()


def build(dest: str, first_day: int | None = None, last_day: int | None = None, choices: dict | None = None, default: str = "rm") -> bytes:
    """Both phases at once (tests, and anything that cannot ask the person)."""
    p = prepare(dest, first_day, last_day)
    try:
        return finish(p, choices, default)
    finally:
        p.close()
