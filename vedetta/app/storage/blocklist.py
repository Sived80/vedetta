"""Ignored devices: they do not appear in searches nor in new-device
alerts. List in config/ignored.json (a deploy does not delete it).

Devices are ignored by MAC, IP or name. The name is for phones with a private MAC, which
changes from one network to another while the announced hostname stays the same."""
from ..atomic import write_atomic
import json
import threading
import time
import uuid

from ..scan import dhcp
from ..recognition import naming
from ..recognition.vendor_lookup import is_private_mac

from ..paths import data_path
PATH = data_path("ignored.json")
KINDS = ("mac", "ip", "name")

_lock = threading.Lock()
_cache: dict = {"stamp": None, "items": []}


def _norm(kind: str, value: str) -> str:
    value = (value or "").strip()
    if kind == "mac":
        return value.upper().replace("-", ":")
    if kind == "name":
        return " ".join(value.split()).casefold()
    return value


def list_items() -> list[dict]:
    stamp = _stamp()
    if _cache["stamp"] == stamp and stamp is not None:
        return _cache["items"]
    items = [_clean_entry(it) for it in _read_raw_entries() if _is_valid_entry(it)] if stamp is not None else []
    _cache.update(stamp=stamp, items=items)
    return items


def _stamp():
    try:
        return PATH.stat().st_mtime
    except OSError:
        return None


def _read_raw_entries() -> list:
    """The JSON list stored in the file; empty if the file cannot be read, is not valid JSON or is not a list."""
    try:
        raw = json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return raw if isinstance(raw, list) else []


def _is_valid_entry(it) -> bool:
    """An entry is a dictionary with a known kind and a non-blank text value."""
    if not isinstance(it, dict) or it.get("kind") not in KINDS:
        return False
    return isinstance(it.get("value"), str) and bool(it["value"].strip())


def _clean_entry(it: dict) -> dict:
    return {"id": str(it.get("id", "")), "kind": it["kind"], "value": it["value"].strip(),
            "label": str(it.get("label", ""))[:80], "added": it.get("added")}


def _write(items: list[dict]) -> None:
    write_atomic(PATH, lambda f: json.dump(items, f, ensure_ascii=False, indent=2), ".ignored-")
    _cache["stamp"] = None


def add(kind: str, value: str, label: str = "") -> list[dict]:
    """Adds an entry (if the kind+value pair already exists it does not duplicate). ValueError if invalid."""
    value = (value or "").strip()
    if kind not in KINDS or not 2 <= len(value) <= 80:
        raise ValueError("invalid")
    with _lock:
        items = list(list_items())
        key = _norm(kind, value)
        if not any(i["kind"] == kind and _norm(kind, i["value"]) == key for i in items):
            items.append({"id": uuid.uuid4().hex[:8], "kind": kind, "value": value,
                          "label": (label or value)[:80], "added": int(time.time())})
            _write(items)
        return list_items()


def remove(item_id: str) -> bool:
    with _lock:
        items = list(list_items())
        kept = [i for i in items if i["id"] != item_id]
        if len(kept) == len(items):
            return False
        _write(kept)
        return True


def matches(*, mac: str | None = None, ip: str | None = None, name: str | None = None) -> bool:
    """True if the device is in the list. The name is also compared with
    the one announced via DHCP by the MAC, if known."""
    items = list_items()
    if not items:
        return False
    names = _device_names(mac, name)
    mac_n = _norm("mac", mac) if mac else None
    return any(_entry_matches(it, mac_n, ip, names) for it in items)


def _device_names(mac: str | None, name: str | None) -> set[str]:
    """Normalised names of the device: its own and the hostname announced via DHCP for its MAC."""
    announced = (dhcp.seen.get((mac or "").lower()) or {}).get("hostname")
    return {_norm("name", n) for n in (name, announced) if n}


def _entry_matches(item: dict, mac_n: str | None, ip: str | None, names: set[str]) -> bool:
    """True if one entry of the list refers to the device."""
    kind = item["kind"]
    key = _norm(kind, item["value"])
    if kind == "mac":
        return bool(mac_n) and key == mac_n
    if kind == "ip":
        return bool(ip) and key == ip
    if kind == "name":
        return key in names
    return False


def choose(ip: str | None, mac: str | None, name: str | None) -> tuple[str, str]:
    """How to ignore a device: by name if the MAC is private (it changes) and the
    name is known, otherwise by MAC, otherwise by name, otherwise by IP."""
    hostname = naming.clean_name(name) or naming.clean_name((dhcp.seen.get((mac or "").lower()) or {}).get("hostname"))
    if mac and not (is_private_mac(mac) and hostname):
        return "mac", mac.upper()
    if hostname:
        return "name", hostname
    return "ip", ip or ""


def add_host(ip: str | None, mac: str | None, name: str | None, label: str = "") -> list[dict]:
    kind, value = choose(ip, mac, name)
    return add(kind, value, label or " · ".join(x for x in (name, ip, mac) if x))
