"""Dispositivi ignorati: non compaiono nelle ricerche ne' negli avvisi di nuovo
dispositivo. Elenco in config/ignored.json (un deploy non lo cancella).

Si ignora per MAC, IP o nome. Il nome serve ai telefoni con MAC privato, che
cambia da una rete all'altra mentre l'hostname annunciato resta lo stesso."""
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
    """Aggiunge una voce (se la coppia tipo+valore c'e' gia' non duplica). ValueError se non valida."""
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
    """True se il dispositivo e' nell'elenco. Il nome si confronta anche con
    quello annunciato via DHCP dal MAC, se noto."""
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
    """Come ignorare un dispositivo: per nome se il MAC e' privato (cambia) e il
    nome e' noto, altrimenti per MAC, altrimenti per nome, altrimenti per IP."""
    hostname = naming.clean_name(name) or naming.clean_name((dhcp.seen.get((mac or "").lower()) or {}).get("hostname"))
    if mac and not (is_private_mac(mac) and hostname):
        return "mac", mac.upper()
    if hostname:
        return "name", hostname
    return "ip", ip or ""


def add_host(ip: str | None, mac: str | None, name: str | None, label: str = "") -> list[dict]:
    kind, value = choose(ip, mac, name)
    return add(kind, value, label or " · ".join(x for x in (name, ip, mac) if x))
