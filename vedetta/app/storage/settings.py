"""User settings (config/settings.json):
"alerts" = show the alerts (new open port, new device...);
"poll_interval" = seconds between one check and the next (fixed values);
"phone_hold_ha" = a silent phone that a router tracker of Home Assistant says is at home stays online (ha/tracker_hold.py, 1.0.3);
"group_order" = the order of the groups on the page, the same on every device ([] = the default order, device_groups.TYPE_ORDER; 1.0.4).
Unknown keys are ignored: the file contains only the known ones."""
from ..atomic import write_atomic
from .. import device_groups
import functools
import ipaddress
import json
import logging
import re
import shutil
import threading
import time

from ..scan import flows
from ..scan.scan_common import NO_REQUEST_PORTS

from ..paths import DATA_DIR as CONFIG_DIR
SETTINGS_PATH = CONFIG_DIR / "settings.json"

logger = logging.getLogger("dashboard")

_LOCK = threading.RLock()   # one lock for every read - modify - write of settings.json (as devices_config): each change re-reads the other keys and writes the whole file


def _locked(function):
    """The whole sequence of a modifying function (read, change, save) runs under the lock; reentrant, so a function may call another."""
    @functools.wraps(function)
    def run(*args, **kwargs):
        with _LOCK:
            return function(*args, **kwargs)
    return run

# Allowed check interval (seconds). Note: with MISS_LIMIT (state.py)
# a device is reported offline after 3 failed checks, so the
# detection delay scales with the interval (30 s -> ~90 s, 5 min -> ~15 min).
POLL_INTERVALS = (10, 15, 30, 60, 120, 300)
_NOTIFY_SERVICE = re.compile(r"notify\.[a-z0-9_]{1,80}")   # a service of the notify domain, as Home Assistant names them

# Consecutive failed checks before declaring a device offline (hysteresis):
# higher = fewer false "offline" (sleeping phones), but slower detection.
MISS_LIMITS = (1, 2, 3, 5, 10)

DEFAULTS: dict = {"alerts": True, "poll_interval": 30, "miss_limit": 3, "phone_hold_ha": True, "group_order": []}

# The Sentinel's way out (ha/ha_notify.py), keys of the file apart from DEFAULTS like the mqtt_* ones (not in load()/update()):
# "ha_events" = vedetta_* events on the bus of Home Assistant; "notify_order" = the recipients in their order, each with the wait after
# the one before ([{"service": "notify.x", "delay_s": 30}, ...], ha/notify_queue.py); "notify_service" = the single service of 0.99.x,
# read once into notify_order and then left empty.
SENTINEL_DEFAULTS: dict = {"ha_events": False, "notify_service": "", "notify_order": []}
NOTIFY_DELAYS = (0, 30, 60, 120, 300, 600)   # seconds after the recipient before
NOTIFY_MAX = 8

# The ARP table of the router through SNMP (scan/snmp.py), keys apart too: the router's address and the community the person writes.
# Off while either is empty; the community never leaves snmp_load() (the page gets snmp_public()).
SNMP_DEFAULTS: dict = {"snmp_router": "", "snmp_community": ""}

# Publishing to Home Assistant (ha/mqtt_ha.py, off by default). They are keys
# of the file separate from DEFAULTS: they do not appear in load()/update() (so not even
# in GET /api/settings) and the password never leaves the mqtt_* functions.
MQTT_DEFAULTS: dict = {"mqtt_enabled": False, "mqtt_host": "", "mqtt_port": 1883, "mqtt_user": "", "mqtt_password": ""}


def valid_value(key: str, value) -> bool:
    """Right type (bool does not count as int) and, for the interval, allowed value."""
    if key == "poll_interval":
        return type(value) is int and value in POLL_INTERVALS
    if key == "miss_limit":
        return type(value) is int and value in MISS_LIMITS
    if key == "group_order":
        return device_groups.valid_order(value)
    return isinstance(value, type(DEFAULTS[key]))


def snmp_valid(key: str, value) -> bool:
    if not isinstance(value, str):
        return False
    if key == "snmp_router":
        return value == "" or _is_router_address(value)
    return len(value) <= 64 and value.isprintable()


_PRIVATE = (ipaddress.ip_network("10.0.0.0/8"), ipaddress.ip_network("172.16.0.0/12"), ipaddress.ip_network("192.168.0.0/16"))


def _is_router_address(value: str) -> bool:
    """A router of the house: one private unicast IPv4 address (the community of SNMP v2c travels in clear, so never a public address, a
    broadcast, a multicast, the loopback or 0.0.0.0; an address ending in .0 or .255 is the network or the broadcast of a /24)."""
    try:
        address = ipaddress.IPv4Address(value)                  # also refuses a leading zero ("01.2.3.4"), which _is_ipv4 would let through
    except ValueError:
        return False
    return any(address in net for net in _PRIVATE) and value.split(".")[-1] not in ("0", "255")


def _is_ipv4(value: str) -> bool:
    parts = value.split(".")
    return len(parts) == 4 and all(p.isdigit() and len(p) <= 3 and int(p) <= 255 for p in parts)


def sentinel_valid(key: str, value) -> bool:
    if key == "notify_service":
        return isinstance(value, str) and (value == "" or bool(_NOTIFY_SERVICE.fullmatch(value)))
    if key == "notify_order":
        return _valid_order(value)
    return isinstance(value, type(SENTINEL_DEFAULTS[key]))


def _valid_order(value) -> bool:
    """A list of at most NOTIFY_MAX different recipients, each {"service": a notify service, "delay_s": one of NOTIFY_DELAYS}."""
    if not isinstance(value, list) or len(value) > NOTIFY_MAX:
        return False
    ok = all(isinstance(r, dict) and set(r) == {"service", "delay_s"} and isinstance(r["service"], str) and bool(_NOTIFY_SERVICE.fullmatch(r["service"]))
             and type(r["delay_s"]) is int and r["delay_s"] in NOTIFY_DELAYS for r in value)
    return ok and len({r["service"] for r in value}) == len(value)


def mqtt_valid(key: str, value) -> bool:
    if key == "mqtt_port":
        return type(value) is int and 1 <= value <= 65535 and value not in NO_REQUEST_PORTS      # never a printing or control port: the service would send MQTT bytes there
    if key == "mqtt_host":
        return isinstance(value, str) and len(value) <= 253 and not any(c.isspace() for c in value)
    if key in ("mqtt_user", "mqtt_password"):
        return isinstance(value, str) and len(value) <= 256
    return isinstance(value, type(MQTT_DEFAULTS[key]))


_damaged: dict = {}   # the last damaged settings.json of this run: {"copy": file name or None, "at", "why", "failed"?, "saved_over"?}


def _read_file():
    """The content of settings.json; None when it is missing (a new install) or damaged. A damaged file (not JSON, not an object,
    unreadable) is never lost in silence: before anything is written over it, it is copied aside once as settings.json.broken-<time>
    and the log says so, because the next save would write the defaults (MQTT included) over it."""
    try:
        text = SETTINGS_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        _put_aside(f"unreadable: {exc}")
        return None
    try:
        data = json.loads(text)
    except ValueError as exc:
        _put_aside(f"not JSON: {exc}")
        return None
    if not isinstance(data, dict):
        _put_aside("not a JSON object")
        return None
    return data


def _put_aside(why: str) -> None:
    """Copies the damaged file aside, once per damage (a save over it ends that damage). Never raises: a copy that fails is
    remembered, and then _save refuses to write over the file, so the original stays for whoever can repair it."""
    if _damaged and not _damaged.get("saved_over"):
        return
    stamp = time.strftime("%Y%m%d-%H%M%S")
    copy = SETTINGS_PATH.with_name(f"{SETTINGS_PATH.name}.broken-{stamp}")
    try:
        shutil.copy2(SETTINGS_PATH, copy)
    except OSError as exc:
        _damaged.clear()
        _damaged.update({"copy": None, "at": time.time(), "why": why, "failed": True})
        logger.error("Impostazioni rovinate (%s) e copia non riuscita (%s): non vengono salvate finché il file non si legge", why, exc)
        return
    _damaged.clear()
    _damaged.update({"copy": copy.name, "at": time.time(), "why": why})
    logger.warning("Impostazioni rovinate (%s): copia in %s, si riparte dai valori predefiniti", why, copy.name)


def damaged() -> dict:
    """The damaged settings.json put aside in this run ({} if none): for the journal at start-up."""
    return dict(_damaged)


def load() -> dict:
    """Current settings: the defaults, overwritten by the valid values from the file."""
    result = dict(DEFAULTS)
    data = _read_file()
    if isinstance(data, dict):
        for key in DEFAULTS:
            if key in data and valid_value(key, data[key]):
                result[key] = data[key]
        result["group_order"] = device_groups.full_order(data.get("group_order"))    # written by hand or by a version with other groups: read clean
    return result


def _stored_flows() -> dict[str, list[str]]:
    """Flow profiles saved in the file and valid ("flows" key). A missing
    or invalid profile (file edited by hand) counts as "not configured"."""
    data = _read_file()
    raw = data.get("flows") if isinstance(data, dict) else None
    stored: dict[str, list[str]] = {}
    if isinstance(raw, dict):
        for profile, ids in raw.items():
            try:
                stored[profile] = flows.validate_profile(profile, ids)
            except flows.FlowError:
                logger.warning("Flusso '%s' nelle impostazioni non valido, uso il default", profile)
    return stored


def _stored_mqtt() -> dict:
    """Valid mqtt_* keys present in the file (otherwise the defaults)."""
    result = dict(MQTT_DEFAULTS)
    data = _read_file()
    if isinstance(data, dict):
        for key in MQTT_DEFAULTS:
            if key in data and mqtt_valid(key, data[key]):
                result[key] = data[key]
    return result


def _stored_sentinel() -> dict:
    """Valid keys of the Sentinel present in the file (otherwise the defaults)."""
    data = _read_file()
    data = data if isinstance(data, dict) else {}
    return {key: data[key] if key in data and sentinel_valid(key, data[key]) else default for key, default in SENTINEL_DEFAULTS.items()}


def _stored_snmp() -> dict:
    data = _read_file()
    data = data if isinstance(data, dict) else {}
    return {key: data[key] if key in data and snmp_valid(key, data[key]) else default for key, default in SNMP_DEFAULTS.items()}


def _save_all(data: dict, stored_flows: dict[str, list[str]], mqtt: dict | None = None, sentinel: dict | None = None,
              snmp: dict | None = None) -> None:
    """Saves the simple settings plus the configured flows (if any)
    and the mqtt_* and Sentinel keys already present (never lost by someone else's change); a key at its default is not written."""
    out = dict(data)
    mqtt = _stored_mqtt() if mqtt is None else mqtt
    out.update({k: v for k, v in mqtt.items() if v != MQTT_DEFAULTS[k]})
    sentinel = _stored_sentinel() if sentinel is None else sentinel
    out.update({k: v for k, v in sentinel.items() if v != SENTINEL_DEFAULTS[k]})
    snmp = _stored_snmp() if snmp is None else snmp
    out.update({k: v for k, v in snmp.items() if v != SNMP_DEFAULTS[k]})
    if stored_flows:
        out["flows"] = stored_flows
    _save(out)


def _save(data: dict) -> None:
    """Atomic write: temporary file in the same folder + os.replace
    (like devices_config._save). A damaged file is copied aside first (_read_file): if that copy failed, OSError and nothing is written."""
    if _read_file() is None and _damaged.get("failed") and not _damaged.get("saved_over"):
        raise OSError("settings.json is damaged and could not be copied aside: not saved over it")
    write_atomic(SETTINGS_PATH, lambda f: json.dump(data, f, ensure_ascii=False, indent=2), ".settings-")
    if _damaged:
        _damaged["saved_over"] = True     # the damage is over: a new one later gets its own copy


@_locked
def update(changes: dict) -> dict:
    """Applies only the known keys with the right type, saves, returns everything.
    ValueError if a known key has a value of the wrong type."""
    current = load()
    for key in DEFAULTS:
        if key in changes:
            if not valid_value(key, changes[key]):
                raise ValueError(key)
            current[key] = device_groups.full_order(changes[key]) if key == "group_order" else changes[key]
    _save_all(current, _stored_flows())  # the already configured flows are not lost
    return current


def alerts_enabled() -> bool:
    return bool(load()["alerts"])


def phone_hold_ha() -> bool:
    """The presence of a silent phone held by Home Assistant (the switch in the menu); re-read on every cycle."""
    return bool(load()["phone_hold_ha"])


def miss_limit() -> int:
    """Consecutive failed checks for offline; re-read on every cycle."""
    return int(load()["miss_limit"])


def poll_interval() -> int:
    """Seconds between checks; re-read on every cycle (the change takes effect immediately)."""
    return int(load()["poll_interval"])


# ---- MQTT publishing (mqtt_* keys, never in load()/update()) ----
def mqtt_load() -> dict:
    """Saved MQTT configuration, PASSWORD INCLUDED: for internal use only
    (mqtt_ha); the APIs get mqtt_public()."""
    return _stored_mqtt()


def mqtt_public() -> dict:
    """Like mqtt_load() but without the password (with password_set)."""
    data = _stored_mqtt()
    password = data.pop("mqtt_password")
    data["mqtt_password_set"] = bool(password)
    return data


@_locked
def mqtt_update(changes: dict) -> dict:
    """Applies only the known mqtt_* keys with the right type (ValueError if
    wrong: in that case nothing is saved), atomic write."""
    current = _stored_mqtt()
    for key in MQTT_DEFAULTS:
        if key in changes:
            if not mqtt_valid(key, changes[key]):
                raise ValueError(key)
            current[key] = changes[key]
    _save_all(load(), _stored_flows(), mqtt=current)
    return mqtt_public()


# ---- search flows ("flows" key, never in load()/update() of the simple settings) ----
def flows_load() -> dict[str, list[str]]:
    """Active steps per profile: the default for never-configured profiles."""
    result = flows.default_flows()
    result.update(_stored_flows())
    return result


@_locked
def flows_update(changes: dict) -> dict[str, list[str]]:
    """Validates (even only some profiles), saves, returns the complete flows.
    flows.FlowError (ValueError) if something is not valid: in that case
    nothing is saved."""
    validated = flows.validate_flows(changes)
    stored = _stored_flows()
    stored.update(validated)
    _save_all(load(), stored)
    return flows_load()


@_locked
def flows_reset() -> dict[str, list[str]]:
    """Restores the defaults (removes the "flows" key from the file)."""
    _save_all(load(), {})
    return flows_load()


# ---- the Sentinel's way out (keys apart, never in load()/update()) ----
def sentinel_load() -> dict:
    return _with_order(_stored_sentinel())


def _with_order(cfg: dict) -> dict:
    """The single service of 0.99.x becomes the first of the order (once: the next save empties notify_service)."""
    if cfg["notify_service"] and not cfg["notify_order"]:
        return {**cfg, "notify_order": [{"service": cfg["notify_service"], "delay_s": 0}], "notify_service": ""}
    return {**cfg, "notify_service": ""}


@_locked
def sentinel_update(changes: dict) -> dict:
    """Applies only the known keys with the right value (ValueError if wrong: then nothing is saved), atomic write. A single
    "notify_service" (a page of 0.99.x) is taken as an order of one."""
    wrong = [key for key in SENTINEL_DEFAULTS if key in changes and not sentinel_valid(key, changes[key])]
    if wrong:
        raise ValueError(wrong[0])
    changes = dict(changes)
    if "notify_service" in changes and "notify_order" not in changes:
        changes["notify_order"] = [{"service": changes["notify_service"], "delay_s": 0}] if changes["notify_service"] else []
    changes["notify_service"] = ""
    current = {**sentinel_load(), **{key: changes[key] for key in SENTINEL_DEFAULTS if key in changes}}
    _save_all(load(), _stored_flows(), sentinel=current)
    return current


# ---- the ARP table of the router through SNMP (keys apart, the community never in an answer) ----
def snmp_load() -> dict:
    """With the community: for scan/router_arp.py only."""
    return _stored_snmp()


def snmp_public() -> dict:
    data = _stored_snmp()
    return {"snmp_router": data["snmp_router"], "snmp_community_set": bool(data["snmp_community"])}


@_locked
def snmp_update(changes: dict) -> dict:
    """Applies only the known keys with the right value (ValueError if wrong: then nothing is saved); a community left out is kept."""
    wrong = [key for key in SNMP_DEFAULTS if key in changes and not snmp_valid(key, changes[key])]
    if wrong:
        raise ValueError(wrong[0])
    current = {**_stored_snmp(), **{key: changes[key] for key in SNMP_DEFAULTS if key in changes}}
    _save_all(load(), _stored_flows(), snmp=current)
    return snmp_public()

