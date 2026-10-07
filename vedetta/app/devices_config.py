import os
import tempfile

import yaml

from .paths import DATA_DIR as CONFIG_DIR
DEVICES_PATH = CONFIG_DIR / "devices.yaml"


def _save(data: dict) -> None:
    """Atomic write: temporary file in the same folder + os.replace.
    A crash or an interruption mid-write leaves the previous file
    intact instead of a truncated YAML that would lose all the
    devices."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=CONFIG_DIR, prefix=".devices-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
        os.replace(tmp, DEVICES_PATH)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def load_devices() -> list[dict]:
    if not DEVICES_PATH.exists():
        return []
    data = yaml.safe_load(DEVICES_PATH.read_text(encoding="utf-8")) or {}
    return data.get("devices", [])


def add_devices(new_devices: list[dict]) -> list[dict]:
    """Add devices found with the scanner, avoiding duplicates by IP or id."""
    data = {}
    if DEVICES_PATH.exists():
        data = yaml.safe_load(DEVICES_PATH.read_text(encoding="utf-8")) or {}
    existing = data.setdefault("devices", [])
    existing_ips = {d["ip"] for d in existing}
    existing_ids = {d["id"] for d in existing}

    added = []
    for nd in new_devices:
        if nd["ip"] in existing_ips:
            continue
        device_id = nd.get("id") or f"scan-{nd['ip'].replace('.', '-')}"
        base_id = device_id
        n = 2
        while device_id in existing_ids:
            device_id = f"{base_id}-{n}"
            n += 1
        entry = {"id": device_id, "ip": nd["ip"], "port": nd.get("port", 80), "adapter": nd.get("adapter", "generic")}
        if nd.get("name"):
            entry["name"] = nd["name"]
        if nd.get("scan_info"):
            entry["scan_info"] = nd["scan_info"]
        if nd.get("name_source"):
            entry["name_source"] = nd["name_source"]
        existing.append(entry)
        existing_ids.add(device_id)
        existing_ips.add(nd["ip"])
        added.append(entry)

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _save(data)
    return added


def update_device(device_id: str, new_name: str, new_port: int | None = None, mobile: bool | None = None) -> dict | None:
    """mobile=None lets the name heuristic decide (see probe.py); True/False
    is an explicit user choice, which always beats the heuristic and stays
    valid even if the name changes later (unlike a recognition
    based only on keywords in the name, which is lost as soon as the device has
    a generic name/IP instead of one with "iPhone"/"Pixel"/etc.)."""
    if not DEVICES_PATH.exists():
        return None
    data = yaml.safe_load(DEVICES_PATH.read_text(encoding="utf-8")) or {}
    for d in data.get("devices", []):
        if d["id"] == device_id:
            if new_name != d.get("name"):
                d["name_source"] = "user"  # chosen by hand: scans no longer touch it
            d["name"] = new_name
            if new_port is not None:
                d["port"] = new_port
            if mobile is None:
                d.pop("mobile", None)
            else:
                d["mobile"] = mobile
            _save(data)
            return d
    return None


OVERRIDE_FIELDS = ("brand_user", "type_user", "wol_ok", "ha_share", "focus", "focus_note")
FOCUS_MAX = 5           # devices that can be flagged for the report at the same time
FOCUS_NOTE_MAX = 500


def set_override(device_id: str, field: str, value: str | None) -> dict | None:
    """Brand or type chosen by hand by the user: they stay until set back to automatic
    (value=None) and no scan changes them."""
    if field not in OVERRIDE_FIELDS or not DEVICES_PATH.exists():
        return None
    data = yaml.safe_load(DEVICES_PATH.read_text(encoding="utf-8")) or {}
    for d in data.get("devices", []):
        if d["id"] == device_id:
            if value:
                d[field] = value
            else:
                d.pop(field, None)
            _save(data)
            return d
    return None


def update_ip(device_id: str, new_ip: str) -> str | None:
    """Move the device to a new IP (same appliance that changed address).
    Returns the old IP, None if the device does not exist or the IP already belongs to another."""
    if not DEVICES_PATH.exists():
        return None
    data = yaml.safe_load(DEVICES_PATH.read_text(encoding="utf-8")) or {}
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


def update_auto_name(device_id: str, name: str, source: str, force: bool = False) -> bool:
    """Replace an automatic name with a better one (see naming.is_better); the
    check is redone here on the file, so as not to override a rename made in the meantime."""
    from . import naming
    if not DEVICES_PATH.exists():
        return False
    data = yaml.safe_load(DEVICES_PATH.read_text(encoding="utf-8")) or {}
    for d in data.get("devices", []):
        if d["id"] == device_id:
            if (not force and not naming.is_better(d, source, name)) or d.get("name") == name or d.get("name_source") == "user":
                return False
            d["name"], d["name_source"] = name, source
            _save(data)
            return True
    return False


def update_scan_info(device_id: str, scan_info: dict) -> dict | None:
    """Save the result of the last deep scan (operating system,
    services, page title) so it stays available without having to rescan
    on every dashboard load."""
    if not DEVICES_PATH.exists():
        return None
    data = yaml.safe_load(DEVICES_PATH.read_text(encoding="utf-8")) or {}
    for d in data.get("devices", []):
        if d["id"] == device_id:
            if scan_info:
                d["scan_info"] = scan_info
            else:
                d.pop("scan_info", None)
            _save(data)
            return d
    return None


def remove_device(device_id: str) -> bool:
    if not DEVICES_PATH.exists():
        return False
    data = yaml.safe_load(DEVICES_PATH.read_text(encoding="utf-8")) or {}
    devices = data.get("devices", [])
    remaining = [d for d in devices if d["id"] != device_id]
    if len(remaining) == len(devices):
        return False
    data["devices"] = remaining
    _save(data)
    return True
