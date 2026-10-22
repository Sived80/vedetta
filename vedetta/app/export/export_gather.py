"""export_gather: moved out of export_engine.py (see tools/split_module.py)."""
from pathlib import Path
from .export_estimate import _period_db, filter_jsonl, filter_log
from . import anonymize, export_analysis, network_survey
from ..storage import devices_config, journal, settings
from ..scan import dhcp, mdns_listener
from ..recognition import evidence, roles
from ..ha import ha_data, health_view
from ..scan import host_load
from ..ha import ha_registry, ha_tz, mqtt_ha
import json
from . import export_zip as legacy
from .. import maintenance, paths
import platform
import re
import sqlite3
from ..state import state
import tempfile
import time
import contextlib


JOURNAL_LIMIT = 2000


FORMAT = 2                           # 1 = the old export (lines removed, no period, no destination); 2 = this one


FOCUS_DEFAULT_DAYS = legacy.FOCUS_DAYS


# ------------------------------------------------------------------ phase 1
class Prepared:
    def __init__(self, dest: str) -> None:
        self.dest = dest
        self.files: dict[str, list] = {}          # name -> ["text", str] or ["db", Path]
        self.pending: list[dict] = []             # what is still readable and could not be replaced: the person decides
        self.fixed = 0
        self.manifest: dict = {}
        self.since: float | None = None           # the period that the files cover (None = everything)
        self.until: float | None = None
        self.anon: anonymize.Anonymizer | None = None
        self.want_survey = False                  # the person ticked the network survey (network_survey.add_to decides whether it applies)
        self.survey: dict | None = None           # the survey, once read: the masking is told about its names and addresses
        self.tmp = tempfile.TemporaryDirectory(prefix="vedetta-export-")

    def add(self, name: str, text: str) -> None:
        """A text file of the export."""
        self.files[name] = ["text", text]

    def close(self) -> None:
        with contextlib.suppress(OSError):
            self.tmp.cleanup()


def _gather(p: Prepared, since: float | None, until: float | None) -> None:
    """The raw files (nothing masked yet)."""
    p.since, p.until = since, until
    device_debug_, ha_data_, data_dir, _m = _fill_manifest_header(p)
    _gather_data_files(p, data_dir)
    _gather_database_copy(p, data_dir)
    dbg, evi = _gather_device_debug_and_focus(p, device_debug_, ha_data_)
    _gather_state_snapshots(p, dbg, evi, ha_data_)
    network_survey.add_to(p)


def _fill_manifest_header(p):
    from ..ha.device_debug import device_debug
    device_debug_ = device_debug
    ha_data_ = ha_data
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
    try:
        st = mqtt_ha.service.status()
        m["mqtt"] = {"enabled": bool(st.get("enabled")), "connected": bool(st.get("connected"))}
    except Exception:
        m["mqtt"] = {"enabled": False, "connected": False}
    try:
        m["health"] = health_view.manifest_part()      # counts and seconds of the health judge: no address, no name
    except Exception as exc:
        m["notes"].append(f"health: {exc!r}")
    try:
        m["host_load"] = host_load.manifest_part()     # pressure of the system, numbers only
    except Exception as exc:
        m["notes"].append(f"host_load: {exc!r}")
    return device_debug_, ha_data_, data_dir, m


def _gather_data_files(p, data_dir):
    m = p.manifest
    m["phone_merge"] = state.merge_report
    try:
        m["service"] = state.diagnostics()      # sizes, times and counts of the service: no address, no name
    except Exception as exc:
        m["notes"].append(f"service: {exc!r}")
    m["period"] = {"from": p.since, "until": p.until, "all": p.since is None}
    if data_dir.exists():
        for f in sorted(data_dir.iterdir(), key=lambda f: f.name.lower()):   # same order on every platform (Path ordering is case-sensitive only on POSIX)
            if not _is_skipped_data_file(f):
                _collect_data_file(p, f)


def _is_skipped_data_file(f: Path) -> bool:
    """What is not copied: anything but a file, the database (copied apart), the mapping file and the names that may hold a credential."""
    return not f.is_file() or f.name.startswith("vedetta.db") or f.name == legacy.MAPPING_FILE or any(w in f.name.lower() for w in legacy.SKIP_WORDS)


def _collect_data_file(p: Prepared, f: Path) -> None:
    try:
        text = _read_data_file(f, p.since)
        if text is None:
            p.manifest["notes"].append(f"{f.name}: binary file not included")
            return
        p.add(f"data/{f.name}", _convert_data_text(f, text, p.since, p.until))
    except Exception as exc:               # an unreadable file must not stop the export
        p.manifest["notes"].append(f"{f.name}: {exc!r}")


def _read_data_file(f: Path, since: float | None) -> str | None:
    """The text of a data file (None if it is not text); without a period the logs are read only as far as their tail."""
    return _text_of(f) if f.suffix not in (".log", ".jsonl") or since is not None else legacy._tail(f, legacy.MAX_LOG_BYTES).decode("utf-8", "replace")


def _text_of(path: Path) -> str | None:
    try:
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _convert_data_text(f: Path, text: str, since: float | None, until: float | None) -> str:
    """Credentials replaced in the json files, the period applied to the logs and journals."""
    if f.suffix == ".json":
        return json.dumps(legacy._redact(json.loads(text)), ensure_ascii=False, indent=1)
    if f.suffix == ".log" and since is not None:
        return filter_log(text, since, until)
    if f.suffix == ".jsonl" and since is not None:
        return filter_jsonl(text, since, until)
    return text


def _gather_database_copy(p, data_dir):
    db = data_dir / "vedetta.db"
    if not db.exists():
        return
    if db.stat().st_size > legacy.MAX_DB_BYTES and p.since is None:
        p.manifest["notes"].append(f"vedetta.db not included ({db.stat().st_size} bytes)")
        return
    try:
        copy = _backup_database(db, Path(p.tmp.name) / "vedetta.db")
        if p.since is not None:
            _period_db(copy, p.since, p.until)
        p.files["data/vedetta.db"] = ["db", copy]
    except Exception as exc:
        p.manifest["notes"].append(f"vedetta.db: {exc!r}")


def _backup_database(db: Path, copy: Path) -> Path:
    """A consistent copy of a database that may be in use (the sqlite backup, read-only on the source)."""
    with contextlib.closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True)) as src, contextlib.closing(sqlite3.connect(copy)) as dst:
        src.backup(dst)
    return copy


def _gather_device_debug_and_focus(p, device_debug_, ha_data_):
    dbg, evi = _collect_device_debug(device_debug_)
    _add_focus_section(p, ha_data_, dbg, evi)
    return dbg, evi


def _collect_device_debug(device_debug_) -> tuple[dict, dict]:
    """The debug and the evidence summary of every device; a device that fails is recorded with its error."""
    dbg, evi = {}, {}
    for did in list(state.devices):
        try:
            debug = device_debug_(did)
            dbg[did] = {"name": state.devices[did].get("name"), "ip": state.devices[did].get("ip"), "debug": debug}
            evi[did] = evidence.summarize(debug, state.devices[did])
        except Exception as exc:
            dbg[did] = {"error": repr(exc)}
    return dbg, evi


def _add_focus_section(p, ha_data_, dbg, evi) -> None:
    """The "device under examination" section."""
    m, since = p.manifest, p.since
    try:
        from ..storage.history import history
        flagged = [c for c in devices_config.load_devices() if c.get("focus")][:devices_config.FOCUS_MAX]
        days = _focus_days(since, p.until)
        h_since = since if since is not None else time.time() - FOCUS_DEFAULT_DAYS * 86400
        focus = {"days": days, "devices": _focus_entries(flagged, ha_data_, dbg, evi, h_since, history)}
        m["focus"] = {"devices": len(focus["devices"]), "with_note": sum(1 for x in focus["devices"] if x["note"]), "days": focus["days"]}
        if focus["devices"]:
            p.add("state/focus.json", json.dumps(focus, ensure_ascii=False, indent=1, default=str))
    except Exception as exc:
        m["notes"].append(f"focus: {exc!r}")


def _focus_days(since: float | None, until: float | None):
    return FOCUS_DEFAULT_DAYS if since is None else max(1, round((until - since) / 86400))


def _clean_note(raw: str | None) -> str | None:
    if not raw:
        return raw
    s = re.sub(r"[\u200b-\u200f\u202a-\u202e\ufeff]", "", str(raw)).strip()
    return s or None


def _focus_entries(flagged: list[dict], ha_data_, dbg: dict, evi: dict, h_since: float, history) -> list[dict]:
    """One entry per flagged device that is still in the state: card, evidence, debug and the history since h_since."""
    entries = []
    for cfg in flagged:
        did = cfg["id"]
        dev = state.devices.get(did)
        if not dev:
            continue
        card = ha_data_.compact_device(dev, cfg)
        card.pop("focus_note", None)
        entries.append({"id": did, "name": dev.get("name"), "note": _clean_note(cfg.get("focus_note")), "card": card, "evidence": evi.get(did),
                        "debug": (dbg.get(did) or {}).get("debug"), "history": history.device_focus(did, h_since)})
    return entries


def _gather_state_snapshots(p, dbg, evi, ha_data_):
    add, since, until = p.add, p.since, p.until
    dump = lambda obj: json.dumps(obj, ensure_ascii=False, indent=1, default=str)             # noqa: E731
    add("state/devices_debug.json", dump(dbg))
    add("state/evidence.json", dump(evi))
    add("state/devices_compact.json", dump(ha_data_.compact_all(state.sorted_devices())))
    try:
        add("state/analysis.json", dump(export_analysis.build_analysis_snapshot()))
    except Exception:
        p.manifest["notes"].append("analysis: unavailable")
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
        p.manifest["notes"].append(f"journal: {exc!r}")
