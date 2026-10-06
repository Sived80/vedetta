"""Export for analysis: a zip file with the data needed to understand why a name, a brand or a
category is wrong. No passwords (the MQTT one is replaced), IPs, MACs and names anonymised only inside the
file (anonymize.py), and no upload: the user downloads the file and hands it over themselves."""
import io
import json
import platform
import sqlite3
import tempfile
import time
import zipfile
from pathlib import Path

from . import anonymize, dhcp, ha_registry, journal, mdns_listener, mqtt_ha, paths, roles, settings
from .state import state

MAPPING_FILE = "export_mapping.local"   # kept next to the data but skipped by the export (see below)
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


def _collect(devices: list[dict]) -> anonymize.Anonymizer:
    """Everything that identifies the user or the household, before the file is written."""
    from . import ha_data
    anon = anonymize.Anonymizer()
    for d in devices:                                   # the main network is found first: it becomes 10.0.0.x
        anon.add_ip(d.get("ip"))
    for d in devices:
        mac, ip = d.get("mac"), d.get("ip")
        anon.add_mac(mac)
        reg, mdns = ha_registry.lookup(mac, ip) or {}, mdns_listener.lookup(mac, ip) or {}
        anon.add_area(reg.get("area"))
        try:
            hint = ha_data.effective_type(d, None)
        except Exception:
            hint = None
        try:
            icon = ha_data.icon_for(d, None, hint)
        except Exception:
            icon = None
        name = d.get("name")
        aliases = [name if name != ip else None, (dhcp.seen.get(str(mac or "").lower()) or {}).get("hostname"),
                   mdns.get("name"), reg.get("name")]
        anon.add_device(aliases, hint, d.get("brand"), icon)
    for table in (dhcp.seen, mdns_listener.by_mac, ha_registry._state["by_mac"]):   # devices known but not on the board
        for mac in table:
            anon.add_mac(mac)
    # names that only live in the registries (a device removed from the board, one Home Assistant knows and the app does not)
    for card in dhcp.seen.values():
        anon.add_names([card.get("hostname")])
    for card in list(mdns_listener.by_mac.values()) + list(mdns_listener.by_ip.values()):
        anon.add_names([card.get("name")], skip=(card.get("model"), card.get("manufacturer")))
    for card in list(ha_registry._state["by_mac"].values()) + list(ha_registry._state["by_ip"].values()):
        anon.add_names([card.get("name")] + list(card.get("entry_titles") or []), card.get("manufacturer"),
                       skip=(card.get("model"), card.get("manufacturer")))
    for area in {c.get("area") for c in list(ha_registry._state["by_mac"].values()) + list(ha_registry._state["by_ip"].values())}:
        anon.add_area(area)
    for table in (mdns_listener.by_ip, ha_registry._state["by_ip"]):
        for ip in table:
            anon.add_ip(ip)
    net = (roles.snapshot().get("internet") or {})
    anon.add_public_ip(net.get("public_ip"))
    for hop in net.get("hops") or []:
        anon.add_public_ip(hop)
    return anon


class MaskingFailed(RuntimeError):
    """Something readable was left in a file after the masking: the export is refused, never delivered half masked."""


def _anonymize_text(name: str, text: str, anon: anonymize.Anonymizer) -> str:
    """JSON and JSON lines are walked (the fields that describe the device stay as they are); the rest is plain text.
    The result is checked: if anything readable is left, the file is masked again as plain text and, if it still
    is not clean, the whole export is refused."""
    try:
        if name.endswith(".json"):
            data = anon.data(json.loads(text))
            if not anon.leaks_data(data):
                return json.dumps(data, ensure_ascii=False, indent=1)
        elif name.endswith(".jsonl"):
            rows = [anon.data(json.loads(line)) if line.strip() else None for line in text.split(chr(10))]
            if not any(anon.leaks_data(r) for r in rows if r is not None):
                return chr(10).join(json.dumps(r, ensure_ascii=False) if r is not None else "" for r in rows)
    except ValueError:
        pass
    out = anon.text(text)
    left = anon.leaks(out)
    if left:
        raise MaskingFailed(f"{name}: {', '.join(left)}")
    return out


def _anonymize_db(path: Path, anon: anonymize.Anonymizer) -> None:
    """Every text value of the copy of the database goes through the same replacement."""
    con = sqlite3.connect(path)
    try:
        con.create_function("anon", 1, lambda v: anon.text(v) if isinstance(v, str) else v)
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for tb in tables:
            for _, col, *_rest in con.execute(f'PRAGMA table_info("{tb}")').fetchall():
                con.execute(f"UPDATE \"{tb}\" SET \"{col}\" = anon(\"{col}\") WHERE typeof(\"{col}\") = 'text'")
        con.commit()
        con.execute("VACUUM")
        for tb in tables:                                # nothing readable may be left in the copy either
            for _, col, *_rest in con.execute(f'PRAGMA table_info("{tb}")').fetchall():
                for (value,) in con.execute(f"SELECT DISTINCT \"{col}\" FROM \"{tb}\" WHERE typeof(\"{col}\") = 'text'"):
                    left = anon.leaks(value)
                    if left:
                        raise MaskingFailed(f"vedetta.db {tb}.{col}: {', '.join(left)}")
    finally:
        con.close()


def _save_mapping(anon: anonymize.Anonymizer) -> None:
    """Placeholder -> real value, kept on this machine only (never in the zip): it tells which device is "iPhone-2"."""
    try:
        (paths.DATA_DIR / MAPPING_FILE).write_text(json.dumps(anon.mapping(), ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


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
    anon = _collect(state.sorted_devices())
    manifest["notes"].append("anonymised: IP addresses (same last number), MAC addresses (same manufacturer prefix), names (numbered labels)")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        def put(name: str, content: bytes | str, text: bool = True):
            if text:
                try:
                    content = _anonymize_text(name, content if isinstance(content, str) else content.decode("utf-8"), anon)
                except UnicodeDecodeError:       # not text: it cannot be anonymised, so it is left out
                    manifest["notes"].append(f"{name}: binary file not included")
                    return
            raw = content.encode("utf-8") if isinstance(content, str) else content
            z.writestr(name, raw)
            manifest["files"][name] = len(raw)

        # data files: configuration, DHCP memory, journal, log (tail only)
        if data_dir.exists():
            for f in sorted(data_dir.iterdir()):
                if not f.is_file() or f.name.startswith("vedetta.db") or f.name == MAPPING_FILE or any(w in f.name.lower() for w in SKIP_WORDS):
                    continue
                try:
                    if f.suffix == ".json":
                        put(f"data/{f.name}", json.dumps(_redact(json.loads(f.read_text(encoding="utf-8"))), ensure_ascii=False, indent=1))
                    elif f.suffix in (".log", ".jsonl"):
                        put(f"data/{f.name}", _tail(f, MAX_LOG_BYTES))
                    else:
                        put(f"data/{f.name}", f.read_bytes())
                except MaskingFailed:
                    raise
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
                        _anonymize_db(copy, anon)
                        put("data/vedetta.db", copy.read_bytes(), text=False)
                except MaskingFailed:
                    raise
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
    _save_mapping(anon)
    return buf.getvalue()
