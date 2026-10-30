"""The devices that Home Assistant sees and Vedetta does not scan ("passive" devices): the switch of the function, the last reading and the devices the user adopted.

Kept in a file of its own (passive_devices.json), NEVER in devices.yaml: devices.yaml is what Vedetta probes every cycle, and a passive device must never be touched
(no ping, no ports). What the user chose by hand (name, type, brand) is kept apart from what Home Assistant said, so a new reading never overwrites it."""
import json
import threading

from .. import atomic, paths
from ..applog import logger

PATH = paths.data_path("passive_devices.json")
ID_PREFIX = "ha-"
EDIT_KEYS = ("name", "type", "brand")
_lock = threading.RLock()
_cache: dict | None = None


def _empty() -> dict:
    return {"enabled": False, "read_at": None, "error": None, "candidates": {}, "adopted": {}}


def is_passive_id(device_id) -> bool:
    return str(device_id or "").startswith(ID_PREFIX)


def id_of(mac: str) -> str:
    return ID_PREFIX + mac.replace(":", "").lower()


def mac_of(device_id: str) -> str | None:
    """The MAC (lowercase, with colons) of a passive id, or None when it is not one."""
    raw = str(device_id or "")[len(ID_PREFIX):] if is_passive_id(device_id) else ""
    if len(raw) != 12 or any(c not in "0123456789abcdef" for c in raw):
        return None
    return ":".join(raw[i:i + 2] for i in range(0, 12, 2))


def _load() -> dict:
    global _cache
    if _cache is None:
        data = _empty()
        try:
            data.update(json.loads(PATH.read_text(encoding="utf-8")))
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            logger.warning("Dispositivi visti tramite Home Assistant: file non leggibile (%s), si riparte vuoti", exc)
        _cache = data
    return _cache


def _save() -> None:
    atomic.write_atomic(PATH, lambda f: json.dump(_cache, f, ensure_ascii=False), "passive_")


def reset_cache() -> None:
    """For the tests: forget what was read, the next call reads the file again."""
    global _cache
    with _lock:
        _cache = None


def snapshot() -> dict:
    """A copy of everything kept (callers never change the live data)."""
    with _lock:
        return json.loads(json.dumps(_load()))


def enabled() -> bool:
    with _lock:
        return bool(_load()["enabled"])


def set_enabled(value: bool) -> None:
    with _lock:
        _load()["enabled"] = bool(value)
        _save()


def record_read(rows: list[dict], ts: float, error: str | None = None) -> None:
    """The result of a reading: the candidates are replaced by what Home Assistant says now; the adopted devices keep their edits and get the latest facts.
    A failed reading (error set) changes nothing but the error."""
    with _lock:
        data = _load()
        data["error"] = error
        if error is None:
            _apply_read(data, rows, ts)
        _save()


def _apply_read(data: dict, rows: list[dict], ts: float) -> None:
    data["read_at"] = ts
    data["candidates"] = {r["mac"]: r for r in rows}
    for mac, item in data["adopted"].items():
        _refresh_adopted(item, data["candidates"].get(mac), ts)


def _refresh_adopted(item: dict, row: dict | None, ts: float) -> None:
    """The latest facts of an adopted device. "Unavailable" (online None) says nothing about the client, so the last known state stays."""
    if not row:
        return
    if row["online"] is None:
        row = {**row, "online": item["row"].get("online")}
    item["row"] = row
    if row["online"]:
        item["online_at"] = ts


def adopt(macs: list[str], ts: float) -> list[str]:
    """Adopts the candidates with these MACs; returns those that were adopted now (unknown or already adopted ones are skipped)."""
    with _lock:
        data = _load()
        done = [m for m in dict.fromkeys(macs) if m in data["candidates"] and m not in data["adopted"]]
        for mac in done:
            data["adopted"][mac] = {"row": data["candidates"][mac], "adopted_at": ts, "edit": {}}
        if done:
            _save()
    return done


def forget(mac: str) -> bool:
    """Takes an adopted device out (it goes back to the list of the candidates, as long as Home Assistant still sees it)."""
    with _lock:
        data = _load()
        if data["adopted"].pop(mac, None) is None:
            return False
        _save()
        return True


def set_edit(mac: str, key: str, value) -> bool:
    """What the user chose by hand for an adopted device; an empty value goes back to what Home Assistant says. False when the device is not adopted."""
    if key not in EDIT_KEYS:
        raise ValueError(key)
    with _lock:
        item = _load()["adopted"].get(mac)
        if item is None:
            return False
        if value:
            item["edit"][key] = value
        else:
            item["edit"].pop(key, None)
        _save()
        return True
