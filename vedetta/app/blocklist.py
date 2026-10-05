"""Ignored devices: they do not appear in searches nor in new-device
alerts. List in config/ignored.json (a deploy does not delete it).

Devices are ignored by MAC, IP or name. The name is for phones with a private MAC, which
changes from one network to another while the announced hostname stays the same."""
import json
import os
import tempfile
import threading
import time
import uuid

from . import dhcp, naming
from .vendor_lookup import is_private_mac

from .paths import data_path
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


def _stamp():
    try:
        return PATH.stat().st_mtime
    except OSError:
        return None


def list_items() -> list[dict]:
    stamp = _stamp()
    if _cache["stamp"] == stamp and stamp is not None:
        return _cache["items"]
    items = []
    if stamp is not None:
        try:
            raw = json.loads(PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = []
        for it in raw if isinstance(raw, list) else []:
            if isinstance(it, dict) and it.get("kind") in KINDS and isinstance(it.get("value"), str) and it["value"].strip():
                items.append({"id": str(it.get("id", "")), "kind": it["kind"], "value": it["value"].strip(),
                              "label": str(it.get("label", ""))[:80], "added": it.get("added")})
    _cache.update(stamp=stamp, items=items)
    return items


def _write(items: list[dict]) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=PATH.parent, prefix=".ignored-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        os.replace(tmp, PATH)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
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
    names = {_norm("name", n) for n in (name, (dhcp.seen.get((mac or "").lower()) or {}).get("hostname")) if n}
    mac_n = _norm("mac", mac) if mac else None
    for it in items:
        key = _norm(it["kind"], it["value"])
        if it["kind"] == "mac" and mac_n and key == mac_n:
            return True
        if it["kind"] == "ip" and ip and key == ip:
            return True
        if it["kind"] == "name" and key in names:
            return True
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
