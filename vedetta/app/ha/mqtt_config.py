"""mqtt_config: moved out of mqtt_ha.py (see tools/split_module.py)."""


# ---------------- configuration ----------------
def _port(value, default: int = 1883) -> int:
    try:
        port = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return port if 1 <= port <= 65535 else default


def resolve_config(stored: dict, env) -> dict | None:
    """Effective configuration, or None if MQTT is off. The environment wins,
    field by field (if user/password are missing the stored one is used)."""
    host = (env.get("VEDETTA_MQTT_HOST") or "").strip()
    if host:
        return _env_config(host, stored, env)
    return _stored_config(stored)


def _env_config(host: str, stored: dict, env) -> dict:
    """Configuration taken from the environment (the host is already known to be set); user/password fall back to the stored ones."""
    return {
        "source": "env", "host": host,
        "port": _port(env.get("VEDETTA_MQTT_PORT"), 1883),
        "user": env.get("VEDETTA_MQTT_USER") or stored.get("mqtt_user") or "",
        "password": env.get("VEDETTA_MQTT_PASSWORD") or stored.get("mqtt_password") or "",
    }


def _stored_config(stored: dict) -> dict | None:
    """Configuration from settings.json, or None if MQTT is not enabled there or has no host."""
    if not (stored.get("mqtt_enabled") and stored.get("mqtt_host")):
        return None
    return {
        "source": "settings", "host": stored["mqtt_host"], "port": _port(stored.get("mqtt_port")),
        "user": stored.get("mqtt_user") or "", "password": stored.get("mqtt_password") or "",
    }
