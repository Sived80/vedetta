"""User settings (config/settings.json):
"alerts" = show the alerts (new open port, new device...);
"poll_interval" = seconds between one check and the next (fixed values).
Unknown keys are ignored: the file contains only the known ones."""
import json
import logging
import os
import tempfile

from . import flows

from .paths import DATA_DIR as CONFIG_DIR
SETTINGS_PATH = CONFIG_DIR / "settings.json"

logger = logging.getLogger("dashboard")

# Allowed check interval (seconds). Note: with MISS_LIMIT (state.py)
# a device is reported offline after 3 failed checks, so the
# detection delay scales with the interval (30 s -> ~90 s, 5 min -> ~15 min).
POLL_INTERVALS = (10, 15, 30, 60, 120, 300)

# Consecutive failed checks before declaring a device offline (hysteresis):
# higher = fewer false "offline" (sleeping phones), but slower detection.
MISS_LIMITS = (1, 2, 3, 5, 10)

DEFAULTS: dict = {"alerts": True, "poll_interval": 30, "miss_limit": 3}

# Publishing to Home Assistant (mqtt_ha.py, off by default). They are keys
# of the file separate from DEFAULTS: they do not appear in load()/update() (so not even
# in GET /api/settings) and the password never leaves the mqtt_* functions.
MQTT_DEFAULTS: dict = {"mqtt_enabled": False, "mqtt_host": "", "mqtt_port": 1883, "mqtt_user": "", "mqtt_password": ""}


def valid_value(key: str, value) -> bool:
    """Right type (bool does not count as int) and, for the interval, allowed value."""
    if key == "poll_interval":
        return type(value) is int and value in POLL_INTERVALS
    if key == "miss_limit":
        return type(value) is int and value in MISS_LIMITS
    return isinstance(value, type(DEFAULTS[key]))


def mqtt_valid(key: str, value) -> bool:
    if key == "mqtt_port":
        return type(value) is int and 1 <= value <= 65535
    if key == "mqtt_host":
        return isinstance(value, str) and len(value) <= 253 and not any(c.isspace() for c in value)
    if key in ("mqtt_user", "mqtt_password"):
        return isinstance(value, str) and len(value) <= 256
    return isinstance(value, type(MQTT_DEFAULTS[key]))


def load() -> dict:
    """Current settings: the defaults, overwritten by the valid values from the file."""
    result = dict(DEFAULTS)
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return result
    if isinstance(data, dict):
        for key, default in DEFAULTS.items():
            if key in data and valid_value(key, data[key]):
                result[key] = data[key]
    return result


def _save(data: dict) -> None:
    """Atomic write: temporary file in the same folder + os.replace
    (like devices_config._save)."""
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=SETTINGS_PATH.parent, prefix=".settings-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, SETTINGS_PATH)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _stored_flows() -> dict[str, list[str]]:
    """Flow profiles saved in the file and valid ("flows" key). A missing
    or invalid profile (file edited by hand) counts as "not configured"."""
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
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
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return result
    if isinstance(data, dict):
        for key in MQTT_DEFAULTS:
            if key in data and mqtt_valid(key, data[key]):
                result[key] = data[key]
    return result


def _save_all(data: dict, stored_flows: dict[str, list[str]], mqtt: dict | None = None) -> None:
    """Saves the simple settings plus the configured flows (if any)
    and the mqtt_* keys already present (never lost by someone else's change)."""
    out = dict(data)
    mqtt = _stored_mqtt() if mqtt is None else mqtt
    out.update({k: v for k, v in mqtt.items() if v != MQTT_DEFAULTS[k]})
    if stored_flows:
        out["flows"] = stored_flows
    _save(out)


def update(changes: dict) -> dict:
    """Applies only the known keys with the right type, saves, returns everything.
    ValueError if a known key has a value of the wrong type."""
    current = load()
    for key, default in DEFAULTS.items():
        if key in changes:
            if not valid_value(key, changes[key]):
                raise ValueError(key)
            current[key] = changes[key]
    _save_all(current, _stored_flows())  # the already configured flows are not lost
    return current


def alerts_enabled() -> bool:
    return bool(load()["alerts"])


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


def flows_update(changes: dict) -> dict[str, list[str]]:
    """Validates (even only some profiles), saves, returns the complete flows.
    flows.FlowError (ValueError) if something is not valid: in that case
    nothing is saved."""
    validated = flows.validate_flows(changes)
    stored = _stored_flows()
    stored.update(validated)
    _save_all(load(), stored)
    return flows_load()


def flows_reset() -> dict[str, list[str]]:
    """Restores the defaults (removes the "flows" key from the file)."""
    _save_all(load(), {})
    return flows_load()
