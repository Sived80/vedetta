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
import sqlite3
import time
import zipfile
from pathlib import Path

from ..storage import devices_config
from ..recognition import evidence
from .. import paths
from . import export_zip as legacy
from ..state import state
from .export_estimate import HORIZON_DAYS, LIMIT_BYTES, MAX_LOG_PERIOD, SEAL_FACTOR, ZIP_RATIO, _TS, _add_database_row_sizes, _add_log_and_data_file_sizes, _cache_estimate_result, _est_cache, _line_ts, _open_estimate_buckets, _period_db, bounds, day_start, estimate, filter_jsonl, filter_log  # noqa: F401
from .export_gather import FOCUS_DEFAULT_DAYS, FORMAT, JOURNAL_LIMIT, Prepared, _add_focus_section, _collect_data_file, _collect_device_debug, _convert_data_text, _fill_manifest_header, _focus_days, _focus_entries, _gather, _gather_data_files, _gather_database_copy, _gather_device_debug_and_focus, _gather_state_snapshots, _is_skipped_data_file, _read_data_file, _text_of  # noqa: F401
from .export_mask import _add_pending, _db_flagged, _fix_databases, _fix_text_files, _flagged, _is_flagged, _line_of, _mask_db, _mask_files, _mask_text, _repair_file  # noqa: F401

REMOVED = "[removed]"
STEPS_DEV = ("collect", "mask", "check", "fix", "seal", "ready")


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
        _mask_files(p, anon)
        note("check")
        flagged_text, flagged_db = _flagged(p, anon)
        if not flagged_text and not flagged_db:
            return p
        note("fix")
        seen: set = set()
        _fix_text_files(p, flagged_text, anon, seen)
        _fix_databases(p, flagged_db, anon, seen)
        return p
    except Exception:
        p.close()
        raise


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
        out_m = m
        if p.dest == "dev" and p.anon is not None:
            out_m = p.anon.data(m)
            if p.anon.leaks_data(out_m):
                out_m, _, _ = p.anon.repair_data(out_m)
        z.writestr("manifest.json", json.dumps(out_m, ensure_ascii=False, indent=1))
    if p.dest == "dev" and p.anon is not None:
        legacy._save_mapping(p.anon)
    return buf.getvalue()


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


def build(dest: str, first_day: int | None = None, last_day: int | None = None, choices: dict | None = None, default: str = "rm") -> bytes:
    """Both phases at once (tests, and anything that cannot ask the person)."""
    p = prepare(dest, first_day, last_day)
    try:
        return finish(p, choices, default)
    finally:
        p.close()
