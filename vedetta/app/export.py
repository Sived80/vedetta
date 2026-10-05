"""Export for analysis: a zip file with the data needed to understand why a name, a brand or a
category is wrong. No passwords (the MQTT one is replaced) and no upload: the user downloads the file
and hands it over themselves."""
import io
import json
import platform
import sqlite3
import tempfile
import time
import zipfile
from pathlib import Path

from . import dhcp, ha_registry, journal, mdns_listener, mqtt_ha, paths, roles, settings
from .state import state

MAX_DB_BYTES = 40 * 1024 * 1024    # above this size the database is not included
MAX_LOG_BYTES = 2 * 1024 * 1024    # for logs only the tail is kept
SKIP_WORDS = ("key", "token", "secret", "pass")   # files that might contain credentials


def _redact(obj):
    """Copy with every field that looks like a credential replaced."""
    if isinstance(obj, dict):
        return {k: ("***" if any(w in str(k).lower() for w in SKIP_WORDS) and v else _redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact(v) for v in obj]
    return obj


def _tail(path: Path, limit: int) -> bytes:
    size = path.stat().st_size
    with path.open("rb") as fh:
        if size > limit:
            fh.seek(size - limit)
            fh.readline()   # whole line
        return fh.read()


def build_zip() -> bytes:
    from .routes_ha import device_debug
    from . import ha_data
    data_dir = paths.DATA_DIR
    manifest = {"created": time.strftime("%Y-%m-%d %H:%M:%S"), "version": mqtt_ha.version(),
                "python": platform.python_version(), "platform": platform.platform(), "files": {}, "notes": []}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        def put(name: str, content: bytes | str):
            raw = content.encode("utf-8") if isinstance(content, str) else content
            z.writestr(name, raw)
            manifest["files"][name] = len(raw)

        # data files: configuration, DHCP memory, journal, log (tail only)
        if data_dir.exists():
            for f in sorted(data_dir.iterdir()):
                if not f.is_file() or f.name.startswith("vedetta.db") or any(w in f.name.lower() for w in SKIP_WORDS):
                    continue
                try:
                    if f.suffix == ".json":
                        put(f"data/{f.name}", json.dumps(_redact(json.loads(f.read_text(encoding="utf-8"))), ensure_ascii=False, indent=1))
                    elif f.suffix in (".log", ".jsonl"):
                        put(f"data/{f.name}", _tail(f, MAX_LOG_BYTES))
                    else:
                        put(f"data/{f.name}", f.read_bytes())
                except Exception as exc:   # an unreadable file must not stop the export
                    manifest["notes"].append(f"{f.name}: {exc!r}")
        # history database: consistent copy (SQLite backup) unless it is huge
        db = data_dir / "vedetta.db"
        if db.exists():
            if db.stat().st_size > MAX_DB_BYTES:
                manifest["notes"].append(f"vedetta.db non incluso ({db.stat().st_size} byte)")
            else:
                try:
                    with tempfile.TemporaryDirectory() as tmp:
                        copy = Path(tmp) / "vedetta.db"
                        src = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
                        dst = sqlite3.connect(copy)
                        src.backup(dst)
                        dst.close(); src.close()
                        put("data/vedetta.db", copy.read_bytes())
                except Exception as exc:
                    manifest["notes"].append(f"vedetta.db: {exc!r}")
        # the current state: why each device is the way it is
        dbg = {}
        for did in list(state.devices):
            try:
                dbg[did] = {"name": state.devices[did].get("name"), "ip": state.devices[did].get("ip"), "debug": device_debug(did)}
            except Exception as exc:
                dbg[did] = {"error": repr(exc)}
        put("state/devices_debug.json", json.dumps(dbg, ensure_ascii=False, indent=1, default=str))
        put("state/devices_compact.json", json.dumps(ha_data.compact_all(state.sorted_devices()), ensure_ascii=False, indent=1, default=str))
        put("state/ha_registry.json", json.dumps({"status": ha_registry.status(), "by_mac": ha_registry._state["by_mac"], "by_ip": ha_registry._state["by_ip"]}, ensure_ascii=False, indent=1, default=str))
        put("state/mdns_seen.json", json.dumps({"by_mac": mdns_listener.by_mac, "by_ip": mdns_listener.by_ip}, ensure_ascii=False, indent=1, default=str))
        put("state/roles.json", json.dumps(roles.snapshot(), ensure_ascii=False, indent=1, default=str))
        put("state/dhcp_seen.json", json.dumps(dhcp.seen, ensure_ascii=False, indent=1, default=str))
        put("state/settings.json", json.dumps(_redact(settings.load()), ensure_ascii=False, indent=1))
        try:
            put("state/journal.json", json.dumps(journal.entries("detail", 500), ensure_ascii=False, indent=1, default=str))
        except Exception as exc:
            manifest["notes"].append(f"journal: {exc!r}")
        put("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
    return buf.getvalue()
