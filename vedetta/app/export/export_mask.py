"""export_mask: moved out of export_engine.py (see tools/split_module.py)."""
from pathlib import Path
from .export_gather import Prepared
from . import anonymize, export_db
import json
import sqlite3


def _mask_files(p: Prepared, anon: anonymize.Anonymizer) -> None:
    for name, entry in p.files.items():
        if entry[0] == "text":
            entry[1] = _mask_text(name, entry[1], anon)
        else:
            _mask_db(entry[1], anon)


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
        export_db.mask_text_columns(con, anon)
    finally:
        con.close()


def _flagged(p: Prepared, anon: anonymize.Anonymizer) -> tuple[list, dict]:
    """What is still readable after the masking: (text files, {database: rows})."""
    flagged_text = [n for n, e in p.files.items() if e[0] == "text" and _is_flagged(n, e[1], anon)]
    flagged_db = {n: _db_flagged(e[1], anon) for n, e in p.files.items() if e[0] == "db"}
    return flagged_text, {n: v for n, v in flagged_db.items() if v}


def _db_flagged(path: Path, anon: anonymize.Anonymizer) -> list[tuple[str, str, str]]:
    con = sqlite3.connect(path)
    try:
        return [(tb, col, value) for tb, col, value in export_db.distinct_texts(con) if anon.leaks(value)]
    finally:
        con.close()


def _is_flagged(name: str, text: str, anon: anonymize.Anonymizer) -> bool:
    try:
        if name.endswith(".json"):
            return bool(anon.leaks_data(json.loads(text)))
        if name.endswith(".jsonl"):
            return any(anon.leaks_data(json.loads(line)) for line in text.split(chr(10)) if line.strip())
    except ValueError:
        pass
    return bool(anon.leaks(text))


def _add_pending(p: Prepared, seen: set, name: str, kind: str, value: str, where: str) -> None:
    """A value that is still readable and could not be replaced: the person decides (each one is listed once)."""
    if (name, kind, value) not in seen:
        seen.add((name, kind, value))
        p.pending.append({"id": len(p.pending), "file": name, "kind": kind, "value": value, "where": where})


def _fix_text_files(p: Prepared, names: list, anon: anonymize.Anonymizer, seen: set) -> None:
    for name in names:
        text, n, left = _repair_file(name, p.files[name][1], anon)
        p.files[name][1] = text
        p.fixed += n
        for kind, value, where in left:
            _add_pending(p, seen, name, kind, value, where)


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


def _line_of(text: str, value: str) -> int:
    return next((i for i, line in enumerate(text.split(chr(10)), 1) if value in line), 0)


def _fix_databases(p: Prepared, flagged_db: dict, anon: anonymize.Anonymizer, seen: set) -> None:
    for name, rows in flagged_db.items():
        con = sqlite3.connect(p.files[name][1])
        try:
            for tb, col, value in rows:
                text, n, left = anon.repair(value)
                if text != value:
                    con.execute(f'UPDATE "{tb}" SET "{col}" = ? WHERE "{col}" = ?', (text, value))
                    p.fixed += n
                for kind, v in left:
                    _add_pending(p, seen, name, kind, v, f"{tb}.{col}")
            con.commit()
        finally:
            con.close()
