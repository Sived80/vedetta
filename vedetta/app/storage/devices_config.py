"""The list of monitored devices, saved in devices.yaml: load, add, update, set by hand (override), change of address, automatic name, scan info, remove."""
from ..atomic import write_atomic

import functools
import threading

import yaml

from ..applog import logger
from ..paths import DATA_DIR as CONFIG_DIR
from ..recognition import naming
DEVICES_PATH = CONFIG_DIR / "devices.yaml"

# devices.yaml is read several times in every cycle of the service: the C parser of libyaml when this PyYAML has it (about ten times faster, the same result: tests/check_yaml_loader.py), else the pure-Python one
_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def _read_yaml(text: str):
    return yaml.load(text, Loader=_LOADER)


_LOCK = threading.RLock()   # one lock for every read - modify - write of devices.yaml: the file is replaced atomically but the SEQUENCE was not (two changes that read the same old file lost one)


def _locked(function):
    """The whole sequence of a modifying function (read, change, save) runs under the lock; reentrant, so a function may call another."""
    @functools.wraps(function)
    def run(*args, **kwargs):
        with _LOCK:
            return function(*args, **kwargs)
    return run


def _edit_card(device_id: str, change) -> dict | None:
    """Read the file, find the card, let `change(card)` modify it; the file is saved when `change` returns anything but False. The card, or None when there is no such card or the change refused."""
    if not DEVICES_PATH.exists():
        return None
    data = _read_yaml(DEVICES_PATH.read_text(encoding="utf-8")) or {}
    for d in data.get("devices", []):
        if d["id"] == device_id:
            if change(d) is False:
                return None
            _save(data)
            return d
    return None


def _save(data: dict) -> None:
    """Atomic write: temporary file in the same folder + os.replace.
    A crash or an interruption mid-write leaves the previous file
    intact instead of a truncated YAML that would lose all the
    devices."""
    write_atomic(DEVICES_PATH, lambda f: yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False), ".devices-", folder=CONFIG_DIR)


def load_devices() -> list[dict]:
    if not DEVICES_PATH.exists():
        return []
    data = _read_yaml(DEVICES_PATH.read_text(encoding="utf-8")) or {}
    return data.get("devices", [])


@_locked
def add_devices(new_devices: list[dict]) -> list[dict]:
    """Add devices found with the scanner, avoiding duplicates by IP or id."""
    data = _load_data()
    existing = data.setdefault("devices", [])
    existing_ips = {d["ip"] for d in existing}
    existing_ids = {d["id"] for d in existing}

    added = []
    for nd in new_devices:
        if nd["ip"] in existing_ips:
            continue
        entry = _new_entry(nd, _unique_device_id(nd, existing_ids))
        entry["seq"] = _take_seq(data)
        existing.append(entry)
        existing_ids.add(entry["id"])
        existing_ips.add(nd["ip"])
        added.append(entry)

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _save(data)
    return added


def _take_seq(data: dict) -> int:
    """The next card number: progressive, never reused (the counter is kept in the file, so removing the highest card does not give its number back)."""
    highest = max((d.get("seq") or 0 for d in data.get("devices", [])), default=0)
    number = max(data.get("next_seq") or 1, highest + 1)
    data["next_seq"] = number + 1
    return number


@_locked
def ensure_seq() -> int:
    """Gives a number to the cards that have none (files of older versions), in the order of the file; how many were numbered. Nothing is written when all have one."""
    data = _load_data()
    missing = [d for d in data.get("devices", []) if d.get("seq") is None]
    for entry in missing:
        entry["seq"] = _take_seq(data)
    if missing:
        _save(data)
    return len(missing)


def ensure_seq_safely() -> int:
    """ensure_seq for the start of the service: a copy of the old file is kept before it is rewritten with the numbers, and a file that cannot be read or written is told in the log and never stops the start."""
    try:
        with _LOCK:
            if DEVICES_PATH.exists() and any(d.get("seq") is None for d in _load_data().get("devices", [])):
                backup = DEVICES_PATH.with_name(DEVICES_PATH.name + ".bak")
                backup.write_bytes(DEVICES_PATH.read_bytes())
            return ensure_seq()
    except Exception:  # noqa: BLE001  (the start of the service must not fail for a file that is damaged: told in the log)
        logger.exception("Numerazione delle schede non riuscita (devices.yaml non leggibile?)")
        return 0


def _load_data() -> dict:
    """The content of devices.yaml (empty dictionary if the file is missing or empty)."""
    if not DEVICES_PATH.exists():
        return {}
    return _read_yaml(DEVICES_PATH.read_text(encoding="utf-8")) or {}


def _unique_device_id(nd: dict, existing_ids: set) -> str:
    """The id of the new device (or one made from its address), with -2, -3... added until it is not taken."""
    device_id = nd.get("id") or f"scan-{nd['ip'].replace('.', '-')}"
    base_id = device_id
    n = 2
    while device_id in existing_ids:
        device_id = f"{base_id}-{n}"
        n += 1
    return device_id


def _new_entry(nd: dict, device_id: str) -> dict:
    """The entry saved for a found device: optional fields only when they are filled."""
    entry = {"id": device_id, "ip": nd["ip"], "port": nd.get("port", 80), "adapter": nd.get("adapter", "generic")}
    for key in ("name", "scan_info", "name_source"):
        if nd.get(key):
            entry[key] = nd[key]
    return entry


@_locked
def update_device(device_id: str, new_name: str, new_port: int | None = None, mobile: bool | None = None) -> dict | None:
    """mobile=None lets the name heuristic decide (see probe.py); True/False
    is an explicit user choice, which always beats the heuristic and stays
    valid even if the name changes later (unlike a recognition
    based only on keywords in the name, which is lost as soon as the device has
    a generic name/IP instead of one with "iPhone"/"Pixel"/etc.)."""
    def change(d: dict) -> None:
        if new_name != d.get("name"):
            d["name_source"] = "user"  # chosen by hand: scans no longer touch it
        d["name"] = new_name
        if new_port is not None:
            d["port"] = new_port
        if mobile is None:
            d.pop("mobile", None)
        else:
            d["mobile"] = mobile
    return _edit_card(device_id, change)


OVERRIDE_FIELDS = ("brand_user", "type_user", "wol_ok", "ha_share", "focus", "focus_note")
FOCUS_MAX = 5           # devices that can be flagged for the report at the same time
FOCUS_NOTE_MAX = 500


@_locked
def set_override(device_id: str, field: str, value: str | None) -> dict | None:
    """Brand or type chosen by hand by the user: they stay until set back to automatic
    (value=None) and no scan changes them."""
    if field not in OVERRIDE_FIELDS:
        return None

    def change(d: dict) -> None:
        if value:
            d[field] = value
        else:
            d.pop(field, None)
    return _edit_card(device_id, change)


@_locked
def update_ip(device_id: str, new_ip: str) -> str | None:
    """Move the device to a new IP (same appliance that changed address).
    Returns the old IP, None if the device does not exist or the IP already belongs to another."""
    if not DEVICES_PATH.exists():
        return None
    data = _read_yaml(DEVICES_PATH.read_text(encoding="utf-8")) or {}
    devices = data.get("devices", [])
    if any(d.get("ip") == new_ip for d in devices):
        return None
    for d in devices:
        if d["id"] == device_id:
            old = d["ip"]
            d["ip"] = new_ip
            if d.get("name") == old:  # the name was the IP itself
                d["name"] = new_ip
            _save(data)
            return old
    return None


@_locked
def swap_ips(id_a: str, id_b: str) -> bool:
    """The two cards exchange their addresses (a device took the address of another that left, and this one takes the address the first left free).
    False if one of them does not exist."""
    if not DEVICES_PATH.exists():
        return False
    data = _read_yaml(DEVICES_PATH.read_text(encoding="utf-8")) or {}
    cards = {d["id"]: d for d in data.get("devices", [])}
    a, b = cards.get(id_a), cards.get(id_b)
    if a is None or b is None or id_a == id_b:
        return False
    old_a, old_b = a["ip"], b["ip"]
    a["ip"], b["ip"] = old_b, old_a
    for card, old in ((a, old_a), (b, old_b)):
        if card.get("name") == old:  # the name was the IP itself
            card["name"] = card["ip"]
    _save(data)
    return True


@_locked
def update_auto_name(device_id: str, name: str, source: str, force: bool = False) -> bool:
    """Replace an automatic name with a better one (see naming.is_better); the
    check is redone here on the file, so as not to override a rename made in the meantime."""
    def change(d: dict) -> bool | None:
        if (not force and not naming.is_better(d, source, name)) or d.get("name") == name or d.get("name_source") == "user":
            return False
        d["name"], d["name_source"] = name, source
    return _edit_card(device_id, change) is not None


@_locked
def update_scan_info(device_id: str, scan_info: dict) -> dict | None:
    """Save the result of the last deep scan (operating system,
    services, page title) so it stays available without having to rescan
    on every dashboard load."""
    def change(d: dict) -> None:
        if scan_info:
            d["scan_info"] = scan_info
        else:
            d.pop("scan_info", None)
    return _edit_card(device_id, change)


@_locked
def remove_device(device_id: str) -> bool:
    if not DEVICES_PATH.exists():
        return False
    data = _read_yaml(DEVICES_PATH.read_text(encoding="utf-8")) or {}
    devices = data.get("devices", [])
    remaining = [d for d in devices if d["id"] != device_id]
    if len(remaining) == len(devices):
        return False
    data["devices"] = remaining
    _save(data)
    return True
