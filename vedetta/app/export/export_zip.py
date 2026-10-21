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
from itertools import chain
from pathlib import Path

from . import anonymize, export_db
from ..storage import journal, settings
from ..scan import dhcp, mdns_listener
from ..recognition import evidence, roles
from ..ha import ha_registry, ha_tz, mqtt_ha
from .. import maintenance, paths
from ..state import state
from ..ha import ha_data, health_view
from ..storage import devices_config
import contextlib

MAPPING_FILE = "export_mapping.local"   # kept next to the data but skipped by the export (see below)
MAX_DB_BYTES = 40 * 1024 * 1024    # above this size the database is not included
MAX_LOG_BYTES = 2 * 1024 * 1024    # for logs only the tail is kept
FOCUS_DAYS = 14                    # history of a flagged device that goes in the export
SKIP_WORDS = ("key", "token", "secret", "pass", "user_lang")   # files that might contain credentials, or the ids of the Home Assistant users


def _redact(obj):
    """Copy with every field that looks like a credential replaced."""
    if isinstance(obj, dict):
        return {k: ("***" if any(w in str(k).lower() for w in SKIP_WORDS) and v else _redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact(v) for v in obj]
    return obj


class MaskingFailed(RuntimeError):
    """Something readable was left in a file after the masking: that file is not delivered, never half masked."""


last_omitted: list[dict] = []     # files left out of the last export (the route tells the person)


def _anonymize_text(name: str, text: str, anon: anonymize.Anonymizer, report: list | None = None) -> str:
    """JSON and JSON lines are walked (the fields that describe the device stay as they are); the rest is plain text.
    The result is checked. If anything readable is left the file is masked again as plain text and, if a few lines still are
    not clean, only those lines are replaced by a note. The file is given up (MaskingFailed) only if that does not work."""
    try:
        done = _mask_structured(name, text, anon)
    except ValueError:
        done = None
    if done is not None:
        return done
    out = anon.text(text)
    left = anon.leaks(out)
    if not left:
        return out
    out, dropped = _clean_lines(out, anon)
    _require_clean(name, out, anon, left)
    if report is not None:
        report.append({"file": name, "lines_removed": sum(dropped.values()), "problem": ", ".join(sorted(dropped))})
    return out


def _clean_lines(text: str, anon: anonymize.Anonymizer) -> tuple[str, dict]:
    """Replaces every line that still has something readable by a note that says only the kind of problem."""
    kept, kinds_count = [], {}
    for line in text.split(chr(10)):
        kinds = anon.leaks(line) if line else []
        for k in kinds:
            kinds_count[k] = kinds_count.get(k, 0) + 1
        kept.append(f"[line removed: {', '.join(kinds)}]" if kinds else line)
    return chr(10).join(kept), kinds_count


def _mask_structured(name: str, text: str, anon: anonymize.Anonymizer) -> str | None:
    """The masked text of a JSON or JSON lines file, or None when it is not one or something readable is left in it."""
    if name.endswith(".json"):
        data = anon.data(json.loads(text))
        return None if anon.leaks_data(data) else json.dumps(data, ensure_ascii=False, indent=1)
    if name.endswith(".jsonl"):
        return _mask_json_lines(text, anon)
    return None


def _mask_json_lines(text: str, anon: anonymize.Anonymizer) -> str | None:
    """JSON lines: every non-blank line is masked; None when any row still has something readable."""
    rows = [anon.data(json.loads(line)) if line.strip() else None for line in text.split(chr(10))]
    if any(anon.leaks_data(r) for r in rows if r is not None):
        return None
    return chr(10).join(json.dumps(r, ensure_ascii=False) if r is not None else "" for r in rows)


def _require_clean(name: str, out: str, anon: anonymize.Anonymizer, left: list) -> None:
    """The text after the lines were replaced must be clean, and a .json file must still be JSON: otherwise the file is given up."""
    if anon.leaks(out) or (name.endswith(".json") and not _is_json(out)):
        raise MaskingFailed(f"{name}: {', '.join(sorted(left))}")


def _is_json(text: str) -> bool:
    try:
        json.loads(text)
    except ValueError:
        return False
    return True


class _Zip:
    """The file being written: every entry goes through put(), which masks it and records it in the manifest."""

    def __init__(self, zf: zipfile.ZipFile, anon: anonymize.Anonymizer, manifest: dict) -> None:
        self.zf, self.anon, self.manifest = zf, anon, manifest

    def put(self, name: str, content: bytes | str, text: bool = True) -> None:
        if text:
            try:
                content = _anonymize_text(name, content if isinstance(content, str) else content.decode("utf-8"), self.anon, self.manifest["lines_removed"])
            except UnicodeDecodeError:       # not text: it cannot be anonymised, so it is left out
                self.manifest["notes"].append(f"{name}: binary file not included")
                return
            except MaskingFailed as exc:     # only this file is left out, and the manifest says why (kinds, never values)
                self.manifest["omitted"].append({"file": name, "problem": str(exc).split(": ", 1)[-1]})
                return
        raw = content.encode("utf-8") if isinstance(content, str) else content
        self.zf.writestr(name, raw)
        self.manifest["files"][name] = len(raw)

    def put_json(self, name: str, obj, **dump) -> None:
        self.put(name, json.dumps(obj, ensure_ascii=False, indent=1, **dump))


def build_zip() -> bytes:
    data_dir = paths.DATA_DIR
    manifest = _new_manifest()
    anon = _collect(state.sorted_devices())
    _describe_service(manifest, _never_analysed())
    manifest["notes"].append("anonymised: IP addresses (same last number), MAC addresses (same manufacturer prefix), names (numbered labels)")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        z = _Zip(zf, anon, manifest)
        _put_data_files(z, data_dir)
        _put_database(z, data_dir)
        dbg, evi = _device_reasons()
        _put_focus(z, dbg, evi)
        _put_state_files(z, dbg, evi)
        z.put("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
    _save_mapping(anon)
    last_omitted[:] = manifest["omitted"]
    return buf.getvalue()


def _collect(devices: list[dict]) -> anonymize.Anonymizer:
    """Everything that identifies the user or the household, before the file is written."""
    anon = anonymize.Anonymizer()
    _add_board_devices(anon, devices)
    _add_registry_names(anon)
    _add_public_addresses(anon)
    return anon


def _add_board_devices(anon: anonymize.Anonymizer, devices: list[dict]) -> None:
    """The devices on the board, with what the registries say about each; then the devices known only from DHCP, mDNS or Home Assistant."""
    for d in devices:                                   # the main network is found first: it becomes 10.0.0.x
        anon.add_ip(d.get("ip"))
    cards = [_board_card(anon, d) for d in devices]
    anon.add_devices(cards)                             # together: a name shared by several devices must not merge them
    for mac in chain(dhcp.seen, mdns_listener.by_mac, ha_registry._state["by_mac"]):   # devices known but not on the board
        anon.add_mac(mac)


def _board_card(anon: anonymize.Anonymizer, d: dict) -> tuple:
    """Registers the MAC and area of one board device and returns (aliases, hint, brand, icon) for add_devices."""
    mac, ip = d.get("mac"), d.get("ip")
    anon.add_mac(mac)
    reg, mdns = ha_registry.lookup(mac, ip) or {}, mdns_listener.lookup(mac, ip) or {}
    anon.add_area(reg.get("area"))
    hint = _safe_call(ha_data.effective_type, d, None)
    icon = _safe_call(ha_data.icon_for, d, None, hint)
    name = d.get("name")
    aliases = [name if name != ip else None, (dhcp.seen.get(str(mac or "").lower()) or {}).get("hostname"),
               mdns.get("name"), reg.get("name")]
    return aliases, hint, d.get("brand"), icon


def _safe_call(fn, *args):
    """The result of fn(*args), or None when it raises."""
    try:
        return fn(*args)
    except Exception:
        return None


def _add_registry_names(anon: anonymize.Anonymizer) -> None:
    """Names that only live in the registries (a device removed from the board, one Home Assistant knows and the app does not), and their areas and addresses."""
    for card in dhcp.seen.values():
        anon.add_names([card.get("hostname")])
    for card in list(mdns_listener.by_mac.values()) + list(mdns_listener.by_ip.values()):
        anon.add_names([card.get("name")], skip=(card.get("model"), card.get("manufacturer")))
    for card in list(ha_registry._state["by_mac"].values()) + list(ha_registry._state["by_ip"].values()):
        anon.add_names([card.get("name")] + list(card.get("entry_titles") or []), card.get("manufacturer"),
                       skip=(card.get("model"), card.get("manufacturer")))
    for area in {c.get("area") for c in list(ha_registry._state["by_mac"].values()) + list(ha_registry._state["by_ip"].values())}:
        anon.add_area(area)
    for ip in chain(mdns_listener.by_ip, ha_registry._state["by_ip"]):
        anon.add_ip(ip)


def _add_public_addresses(anon: anonymize.Anonymizer) -> None:
    """The user's public address and the hops of the route to the internet."""
    net = (roles.snapshot().get("internet") or {})
    anon.add_public_ip(net.get("public_ip"))
    for hop in net.get("hops") or []:
        anon.add_public_ip(hop)


def _save_mapping(anon: anonymize.Anonymizer) -> None:
    """Placeholder -> real value, kept on this machine only (never in the zip): it tells which device is "iPhone-2"."""
    with contextlib.suppress(OSError):
        (paths.DATA_DIR / MAPPING_FILE).write_text(json.dumps(anon.mapping(), ensure_ascii=False, indent=1), encoding="utf-8")


def _new_manifest() -> dict:
    return {"omitted": [], "lines_removed": [], "created": time.strftime("%Y-%m-%d %H:%M:%S"), "version": mqtt_ha.version(),
            "python": platform.python_version(), "platform": platform.platform(), "files": {}, "notes": [], "format": 1}


def _never_analysed():
    """How many devices never had a deep search (None when it cannot be told)."""
    try:
        return sum(1 for d in devices_config.load_devices() if not maintenance.last_deep_attempt(d))
    except Exception:
        return None


def _describe_service(manifest: dict, pending) -> None:
    """Facts that explain the behaviour of the app and say nothing about the person: the hour offset (not the name of the zone),
    whether it came from Home Assistant, and how many devices never had a deep search."""
    manifest["time"] = {"utc_offset": ha_tz.now().strftime("%z"), "from_home_assistant": ha_tz._state["zone"] is not None, "night_hour": maintenance.NIGHT_HOUR}
    manifest["deep_search"] = {"never_analysed": pending, "devices": len(state.devices)}
    try:
        manifest["service"] = state.diagnostics()      # sizes, times and counts of the service: no address, no name
    except Exception as exc:
        manifest["notes"].append(f"service: {exc!r}")
    manifest["phone_merge"] = state.merge_report         # counts: why two cards of the same phone were (not) merged, without any name
    try:
        manifest["health"] = health_view.manifest_part()  # counts and seconds of the health judge: no address, no name
    except Exception as exc:
        manifest["notes"].append(f"health: {exc!r}")


def _put_data_files(z: _Zip, data_dir: Path) -> None:
    """Data files: configuration, DHCP memory, journal, log (tail only)."""
    if not data_dir.exists():
        return
    for f in sorted(data_dir.iterdir(), key=lambda f: f.name.lower()):   # same order on every platform
        if _skip_data_file(f):
            continue
        try:
            _put_one_data_file(z, f)
        except Exception as exc:   # an unreadable file must not stop the export
            z.manifest["notes"].append(f"{f.name}: {exc!r}")


def _skip_data_file(f: Path) -> bool:
    """Not a file to export: directories, the database, the mapping, anything whose name hints at credentials."""
    return not f.is_file() or f.name.startswith("vedetta.db") or f.name == MAPPING_FILE or any(w in f.name.lower() for w in SKIP_WORDS)


def _put_one_data_file(z: _Zip, f: Path) -> None:
    """One data file: JSON is redacted, logs keep their tail, anything else goes as bytes."""
    if f.suffix == ".json":
        z.put(f"data/{f.name}", json.dumps(_redact(json.loads(f.read_text(encoding="utf-8"))), ensure_ascii=False, indent=1))
    elif f.suffix in (".log", ".jsonl"):
        z.put(f"data/{f.name}", _tail(f, MAX_LOG_BYTES))
    else:
        z.put(f"data/{f.name}", f.read_bytes())


def _tail(path: Path, limit: int) -> bytes:
    size = path.stat().st_size
    with path.open("rb") as fh:
        if size > limit:
            fh.seek(size - limit)
            fh.readline()   # whole line
        return fh.read()


def _put_database(z: _Zip, data_dir: Path) -> None:
    """The history database: a consistent copy (SQLite backup), masked, unless it is huge."""
    db = data_dir / "vedetta.db"
    if not db.exists():
        return
    if db.stat().st_size > MAX_DB_BYTES:
        z.manifest["notes"].append(f"vedetta.db non incluso ({db.stat().st_size} byte)")
        return
    try:
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "vedetta.db"
            src = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            dst = sqlite3.connect(copy)
            src.backup(dst)
            dst.close(); src.close()
            _anonymize_db(copy, z.anon)
            z.put("data/vedetta.db", copy.read_bytes(), text=False)
    except MaskingFailed as exc:
        z.manifest["omitted"].append({"file": "data/vedetta.db", "problem": str(exc).split(": ", 1)[-1]})
    except Exception as exc:
        z.manifest["notes"].append(f"vedetta.db: {exc!r}")


def _anonymize_db(path: Path, anon: anonymize.Anonymizer) -> None:
    """Every text value of the copy of the database goes through the same replacement."""
    con = sqlite3.connect(path)
    try:
        export_db.mask_text_columns(con, anon)
        for tb, col, value in export_db.distinct_texts(con):         # nothing readable may be left in the copy either
            left = anon.leaks(value)
            if left:
                raise MaskingFailed(f"vedetta.db {tb}.{col}: {', '.join(left)}")
    finally:
        con.close()


def _device_reasons() -> tuple[dict, dict]:
    """The current state: why each device is the way it is ({id: debug}, {id: evidence summary})."""
    from ..ha.device_debug import device_debug
    dbg, evi = {}, {}
    for did in list(state.devices):
        try:
            debug = device_debug(did)
            dbg[did] = {"name": state.devices[did].get("name"), "ip": state.devices[did].get("ip"), "debug": debug}
            evi[did] = evidence.summarize(debug, state.devices[did])        # certainty and rejected hypotheses, as the sheet shows them
        except Exception as exc:
            dbg[did] = {"error": repr(exc)}
    return dbg, evi


def _put_focus(z: _Zip, dbg: dict, evi: dict) -> None:
    """The "device under examination" section: what the person flagged, with a note, so the reader knows where to look."""
    try:
        from ..storage.history import history as _history
        flagged = [c for c in devices_config.load_devices() if c.get("focus")][:devices_config.FOCUS_MAX]
        focus = {"days": FOCUS_DAYS, "devices": []}
        since = time.time() - FOCUS_DAYS * 86400
        for cfg in flagged:
            did = cfg["id"]
            dev = state.devices.get(did)
            if not dev:
                continue
            card = ha_data.compact_device(dev, cfg)
            card.pop("focus_note", None)                         # the note is in its own field, masked as free text
            focus["devices"].append({"id": did, "name": dev.get("name"), "note": z.anon.text_note(cfg.get("focus_note")),
                                     "card": card, "evidence": evi.get(did), "debug": (dbg.get(did) or {}).get("debug"),
                                     "history": _history.device_focus(did, since)})
        z.manifest["focus"] = {"devices": len(focus["devices"]), "with_note": sum(1 for x in focus["devices"] if x["note"]), "days": FOCUS_DAYS}
        if focus["devices"]:
            z.put_json("state/focus.json", focus, default=str)
    except Exception as exc:
        z.manifest["notes"].append(f"focus: {exc!r}")


def _put_state_files(z: _Zip, dbg: dict, evi: dict) -> None:
    z.put_json("state/devices_debug.json", dbg, default=str)
    z.put_json("state/evidence.json", evi, default=str)
    z.put_json("state/devices_compact.json", ha_data.compact_all(state.sorted_devices()), default=str)
    z.put_json("state/ha_registry.json", {"status": ha_registry.status(), "by_mac": ha_registry._state["by_mac"], "by_ip": ha_registry._state["by_ip"]}, default=str)
    z.put_json("state/mdns_seen.json", {"by_mac": mdns_listener.by_mac, "by_ip": mdns_listener.by_ip}, default=str)
    z.put_json("state/roles.json", roles.snapshot(), default=str)
    z.put_json("state/dhcp_seen.json", dhcp.seen, default=str)
    z.put_json("state/settings.json", _redact(settings.load()))
    try:
        z.put_json("state/journal.json", journal.entries("detail", 500), default=str)
    except Exception as exc:
        z.manifest["notes"].append(f"journal: {exc!r}")
