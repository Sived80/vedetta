"""mqtt_payloads: moved out of mqtt_ha.py (see tools/split_module.py)."""
from pathlib import Path
import json
import os
import re
import time
import zlib


STATUS_TOPIC = "vedetta/status"


DISCOVERY_PREFIX = "homeassistant"


SCAN_TOPIC = "vedetta/hub/scan/set"


HUB_STATE_TOPIC = "vedetta/hub/state"


HUB_ID = "vedetta_hub"


_SLUG_RE = re.compile(r"[^a-z0-9_-]+")


def version() -> str:
    """Version from the environment or from the VERSION file in the root (or in the image)."""
    env = os.environ.get("VEDETTA_VERSION", "").strip()
    if env:
        return env
    try:
        return (Path(__file__).resolve().parent.parent.parent / "VERSION").read_text(encoding="utf-8").strip() or "dev"
    except OSError:
        return "dev"


# ---------------- building topics and payloads (pure) ----------------
def slug(device_id: str) -> str:
    """Identifier suitable for topics and unique_id: lowercase, [a-z0-9_-]. If the
    cleanup alters the id a CRC is appended, so two different ids do not collide."""
    raw = str(device_id)
    clean = _SLUG_RE.sub("_", raw.lower()).strip("_") or "x"
    if clean != raw:
        clean += "_" + format(zlib.crc32(raw.encode("utf-8")) & 0xFFFFFF, "06x")
    return clean


def config_topic(object_id: str) -> str:
    return f"{DISCOVERY_PREFIX}/device/{object_id}/config"


def _origin() -> dict:
    return {"name": "Vedetta", "sw": version()}


def device_topics(device_id: str) -> dict[str, str]:
    base = "vedetta/dev/" + slug(device_id)
    return {"config": config_topic("vedetta_" + slug(device_id)),
            "state": base + "/state", "attrs": base + "/attrs", "latency": base + "/latency"}


def _device_components(uid: str, topics: dict[str, str], dev: dict, with_latency: bool) -> dict[str, dict]:
    """Entities published under the device in Home Assistant (tracker, connectivity, IP sensor, latency).
    Extensible: future diagnostic or state entities (e.g. MAC, vendor, RSSI, open ports)
    can be plugged here as additional entries reading from topics['attrs'] or dedicated topics."""
    cmps = {
        "tracker": {
            "p": "device_tracker", "unique_id": uid + "_tracker", "name": None,
            "state_topic": topics["state"], "json_attributes_topic": topics["attrs"],
            "source_type": "router", "payload_home": "home", "payload_not_home": "not_home",
        },
        "connectivity": {
            "p": "binary_sensor", "unique_id": uid + "_connectivity", "name": "Connectivity",
            "device_class": "connectivity", "state_topic": topics["state"],
            "payload_on": "home", "payload_off": "not_home",
        },
        "ip": {
            "p": "sensor", "unique_id": uid + "_ip", "name": "IP Address",
            "state_topic": topics["attrs"], "value_template": "{{ value_json.ip }}",
            "entity_category": "diagnostic", "icon": "mdi:ip-network",
        },
    }
    if with_latency:
        cmps["latency"] = {
            "p": "sensor", "unique_id": uid + "_latency", "name": "Latency",
            "unit_of_measurement": "ms", "device_class": "duration", "state_class": "measurement",
            "entity_category": "diagnostic", "state_topic": topics["latency"],
        }
    return cmps


def device_config(dev: dict, kind: str | None, with_latency: bool) -> dict:
    """Discovery payload of a network device: device_tracker,
    connectivity binary_sensor, IP sensor and (if the latency is known) latency sensor."""
    sid = slug(dev["id"])
    uid = "vedetta_" + sid
    topics = device_topics(dev["id"])
    device = {
        "identifiers": [uid],
        "name": dev.get("name") or dev.get("ip") or dev["id"],
        "via_device": HUB_ID,
    }
    # No "connections" with the MAC: HA would merge this device with the real one (Shelly, TV...) instead of keeping it
    # under "Vedetta". The network device is a sub-device of Vedetta (via_device).
    brand = dev.get("brand") or dev.get("vendor")
    if brand:
        device["manufacturer"] = brand
    if kind:
        device["model"] = kind
    cmps = _device_components(uid, topics, dev, with_latency)
    return {"dev": device, "o": _origin(), "cmps": cmps, "availability_topic": STATUS_TOPIC}


def device_attrs(dev: dict, kind: str | None) -> dict:
    return {
        "ip": dev.get("ip"), "mac": dev.get("mac"),
        "brand": dev.get("brand") or dev.get("vendor"), "type": kind,
        "latency_ms": dev.get("latency_ms"),
        "last_seen": None if dev.get("online") else _fmt_time(dev.get("last_seen")),
        "source_type": "router",
    }


def _fmt_time(ts) -> str | None:
    if not ts:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(ts))


def hub_config() -> dict:
    return {
        "dev": {"identifiers": [HUB_ID], "name": "Vedetta", "manufacturer": "Vedetta",
                "model": "Network dashboard", "sw_version": version()},
        "o": _origin(),
        "cmps": {
            "online": _sensor("online", "Devices online"),
            "offline": _sensor("offline", "Devices offline"),
            "mobile_online": _sensor("mobile_online", "Mobile devices online"),
            "new_devices": _sensor("new_devices", "New devices"),
            "latency_avg": _sensor("latency_avg", "Average latency", "ms"),
            "scan": {"p": "button", "unique_id": HUB_ID + "_scan", "name": "Scan now",
                     "command_topic": SCAN_TOPIC, "payload_press": "PRESS"},
        },
        "availability_topic": STATUS_TOPIC,
    }


def _sensor(key: str, name: str, unit: str | None = None) -> dict:
    c = {"p": "sensor", "unique_id": f"{HUB_ID}_{key}", "name": name, "state_topic": HUB_STATE_TOPIC,
         "value_template": "{{ value_json.%s }}" % key, "state_class": "measurement"}
    if unit:
        c["unit_of_measurement"] = unit
        c["device_class"] = "duration"
    return c


def hub_state(devices: list[dict], new_count: int) -> dict:
    online = [d for d in devices if d.get("online")]
    lat = [d["latency_ms"] for d in online if d.get("latency_ms") is not None]
    return {
        "online": len(online), "offline": len(devices) - len(online),
        "mobile_online": sum(1 for d in online if d.get("is_mobile")),
        "new_devices": new_count,
        "latency_avg": round(sum(lat) / len(lat)) if lat else None,
    }


def _j(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_desired(devices: dict[str, dict], kinds: dict[str, str], new_count: int,
                  latency_seen: set[str], shared: set[str] | None = None) -> dict[str, str]:
    """Map of topic -> payload for everything that must be published right now.
    latency_seen: ids of the devices whose latency has been known at least
    once (it stays a stable entity even when the measurement is missing); updated here.
    shared: ids of the devices the user chose to share with HA (None = all, for tests); the others
    are not published and, if they had been published, disappear from HA (see Sync.diff). Vedetta's counters
    always count all the devices."""
    out: dict[str, str] = {config_topic(HUB_ID): _j(hub_config()),
                           HUB_STATE_TOPIC: _j(hub_state(list(devices.values()), new_count))}
    for did, dev in devices.items():
        if _is_published(did, shared):
            _add_device_entries(out, did, dev, kinds.get(did), latency_seen)
    latency_seen.intersection_update(devices if shared is None else {d for d in devices if d in shared})  # gone/not shared: out of memory
    return out


def _add_device_entries(out: dict[str, str], did: str, dev: dict, kind: str | None, latency_seen: set[str]) -> None:
    """Adds the config, state, attrs (and, once its latency was known, latency) entries of one shared device, in this order."""
    if dev.get("latency_ms") is not None:
        latency_seen.add(did)
    topics = device_topics(did)
    out[topics["config"]] = _j(device_config(dev, kind, did in latency_seen))
    out[topics["state"]] = "home" if dev.get("online") else "not_home"
    out[topics["attrs"]] = _j(device_attrs(dev, kind))
    if did in latency_seen:
        lat = dev.get("latency_ms")
        out[topics["latency"]] = str(round(lat)) if lat is not None else "None"


def _is_published(did: str, shared: set[str] | None) -> bool:
    return shared is None or did in shared
