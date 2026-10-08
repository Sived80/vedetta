"""Publishes Vedetta's state over MQTT using Home Assistant's "device"
discovery (homeassistant/device/<id>/config). Off by default.

Configuration: settings.json (mqtt_enabled, mqtt_host, mqtt_port, mqtt_user,
mqtt_password) or the environment variables VEDETTA_MQTT_HOST/PORT/USER/PASSWORD,
which take precedence (if the host is set, MQTT is active: this is the HA add-on case).

Structure:
- pure functions (resolve_config, slug, build_desired) and the Sync class: they build
  the desired "topic -> payload" map and derive only the differences from it
  (testable without a broker, see tests/check_mqtt_ha.py);
- MqttService: paho-mqtt 2.x client in its own thread (automatic reconnection,
  LWT on vedetta/status) plus an asyncio task that listens to the
  state.subscribe() bus and publishes only the changes.
Does not import state/applog at module level: it comes from start()."""
import asyncio
import json
import logging
import os
import re
import time
import zlib
from pathlib import Path

from ..storage import settings

logger = logging.getLogger("dashboard")

STATUS_TOPIC = "vedetta/status"
HA_STATUS_TOPIC = "homeassistant/status"
DISCOVERY_PREFIX = "homeassistant"
SCAN_TOPIC = "vedetta/hub/scan/set"
HUB_STATE_TOPIC = "vedetta/hub/state"
HUB_ID = "vedetta_hub"
PERIODIC_SECONDS = 60  # counters refresh even without events
WATCHED_EVENTS = ("device", "removed", "new_devices")

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
        return {
            "source": "env", "host": host,
            "port": _port(env.get("VEDETTA_MQTT_PORT"), 1883),
            "user": env.get("VEDETTA_MQTT_USER") or stored.get("mqtt_user") or "",
            "password": env.get("VEDETTA_MQTT_PASSWORD") or stored.get("mqtt_password") or "",
        }
    if stored.get("mqtt_enabled") and stored.get("mqtt_host"):
        return {
            "source": "settings", "host": stored["mqtt_host"], "port": _port(stored.get("mqtt_port")),
            "user": stored.get("mqtt_user") or "", "password": stored.get("mqtt_password") or "",
        }
    return None


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


def _fmt_time(ts) -> str | None:
    if not ts:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(ts))


def device_topics(device_id: str) -> dict[str, str]:
    base = "vedetta/dev/" + slug(device_id)
    return {"config": config_topic("vedetta_" + slug(device_id)),
            "state": base + "/state", "attrs": base + "/attrs", "latency": base + "/latency"}


def device_config(dev: dict, kind: str | None, with_latency: bool) -> dict:
    """Discovery payload of a network device: device_tracker,
    connectivity binary_sensor and (if the latency is known) latency sensor."""
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
    }
    if with_latency:
        cmps["latency"] = {
            "p": "sensor", "unique_id": uid + "_latency", "name": "Latency",
            "unit_of_measurement": "ms", "device_class": "duration", "state_class": "measurement",
            "entity_category": "diagnostic", "state_topic": topics["latency"],
        }
    return {"dev": device, "o": _origin(), "cmps": cmps, "availability_topic": STATUS_TOPIC}


def device_attrs(dev: dict, kind: str | None) -> dict:
    return {
        "ip": dev.get("ip"), "mac": dev.get("mac"),
        "brand": dev.get("brand") or dev.get("vendor"), "type": kind,
        "latency_ms": dev.get("latency_ms"),
        "last_seen": None if dev.get("online") else _fmt_time(dev.get("last_seen")),
        "source_type": "router",
    }


def hub_config() -> dict:
    def sensor(key: str, name: str, unit: str | None = None) -> dict:
        c = {"p": "sensor", "unique_id": f"{HUB_ID}_{key}", "name": name, "state_topic": HUB_STATE_TOPIC,
             "value_template": "{{ value_json.%s }}" % key, "state_class": "measurement"}
        if unit:
            c["unit_of_measurement"] = unit
            c["device_class"] = "duration"
        return c
    return {
        "dev": {"identifiers": [HUB_ID], "name": "Vedetta", "manufacturer": "Vedetta",
                "model": "Network dashboard", "sw_version": version()},
        "o": _origin(),
        "cmps": {
            "online": sensor("online", "Devices online"),
            "offline": sensor("offline", "Devices offline"),
            "mobile_online": sensor("mobile_online", "Mobile devices online"),
            "new_devices": sensor("new_devices", "New devices"),
            "latency_avg": sensor("latency_avg", "Average latency", "ms"),
            "scan": {"p": "button", "unique_id": HUB_ID + "_scan", "name": "Scan now",
                     "command_topic": SCAN_TOPIC, "payload_press": "PRESS"},
        },
        "availability_topic": STATUS_TOPIC,
    }


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
        if shared is not None and did not in shared:
            continue
        if dev.get("latency_ms") is not None:
            latency_seen.add(did)
        topics = device_topics(did)
        kind = kinds.get(did)
        out[topics["config"]] = _j(device_config(dev, kind, did in latency_seen))
        out[topics["state"]] = "home" if dev.get("online") else "not_home"
        out[topics["attrs"]] = _j(device_attrs(dev, kind))
        if did in latency_seen:
            out[topics["latency"]] = "None" if dev.get("latency_ms") is None else str(dev["latency_ms"])
    latency_seen.intersection_update(devices if shared is None else {d for d in devices if d in shared})  # gone/not shared: out of memory
    return out


class Sync:
    """Keeps the last payload sent per topic and returns only the differences;
    topics that disappeared from the desired map receive the empty payload (retained):
    on config topics this is how HA removes the device and entities."""

    def __init__(self) -> None:
        self._sent: dict[str, str | None] = {}

    def adopt(self, topic: str, payload: str) -> None:
        """A "retained" Vedetta message already present on the broker (from a previous version or before a restart):
        it is remembered, so that if it is no longer needed (device not shared) the diff deletes it from HA."""
        self._sent.setdefault(topic, payload)

    def reset(self) -> None:
        """After a (re)connection or an 'online' from HA: everything is resent, but the
        topics already used are remembered (to be able to remove the ones that disappeared)."""
        for topic in self._sent:
            self._sent[topic] = None

    def diff(self, desired: dict[str, str]) -> list[tuple[str, str]]:
        msgs: list[tuple[str, str]] = []
        for topic in [t for t in self._sent if t not in desired]:
            msgs.append((topic, ""))
            del self._sent[topic]
        for topic, payload in desired.items():
            if self._sent.get(topic) != payload:
                msgs.append((topic, payload))
                self._sent[topic] = payload
        # configs before states (HA wants them in this order at creation)
        msgs.sort(key=lambda m: 0 if m[0].endswith("/config") else 1)
        return msgs


# ---------------- service ----------------
class MqttService:
    def __init__(self) -> None:
        self.client = None
        self.cfg: dict | None = None
        self.connected = False
        self.last_error = ""
        self.sync = Sync()
        self._state = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None
        self._latency_seen: set[str] = set()
        self._adopt_timer = None
        self._new_count = 0
        self._started = False

    # ---- lifecycle ----
    async def start(self, state) -> None:
        """Start from the lifespan: always safe, even with MQTT off."""
        self._state = state
        self._loop = asyncio.get_running_loop()
        self._started = True
        self._new_count = len(getattr(state, "_newdev_macs", ()) or ())
        self._task = asyncio.create_task(self._run())
        await self._apply_config()

    async def stop(self) -> None:
        self._started = False
        if self._task:
            self._task.cancel()
            self._task = None
        await self._stop_client()

    async def reconfigure(self) -> None:
        """After a settings change: reconnects with the new configuration."""
        if not self._started:
            return
        await self._stop_client()
        await self._apply_config()

    async def _apply_config(self) -> None:
        try:
            self.cfg = resolve_config(settings.mqtt_load(), os.environ)
        except Exception:
            logger.exception("MQTT: configurazione non leggibile")
            self.cfg = None
        if not self.cfg:
            return
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            self.last_error = "paho-mqtt non installato"
            logger.warning("MQTT attivo in configurazione ma paho-mqtt manca")
            return
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="vedetta-" + format(os.getpid(), "x"))
        if self.cfg["user"]:
            client.username_pw_set(self.cfg["user"], self.cfg["password"] or None)
        client.will_set(STATUS_TOPIC, "offline", qos=1, retain=True)
        client.reconnect_delay_set(min_delay=1, max_delay=60)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        self.client = client
        self.last_error = ""
        try:
            client.connect_async(self.cfg["host"], self.cfg["port"], keepalive=30)
            client.loop_start()
            logger.info("MQTT: connessione a %s:%s (%s)", self.cfg["host"], self.cfg["port"], self.cfg["source"])
        except Exception as exc:
            self.last_error = str(exc)
            logger.warning("MQTT: avvio fallito: %s", exc)

    async def _stop_client(self) -> None:
        client, self.client = self.client, None
        was_connected, self.connected = self.connected, False
        if client is None:
            return

        def close() -> None:
            try:
                if was_connected:
                    client.publish(STATUS_TOPIC, "offline", qos=1, retain=True).wait_for_publish(2)
                client.disconnect()
            except Exception:
                pass
            client.loop_stop()

        await asyncio.to_thread(close)

    # ---- paho callbacks (network thread) ----
    def _on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:
        if getattr(reason_code, "is_failure", False):
            self.last_error = str(reason_code)
            logger.warning("MQTT: connessione rifiutata: %s", reason_code)
            return
        self.connected = True
        self.last_error = ""
        client.publish(STATUS_TOPIC, "online", qos=1, retain=True)
        # besides the command and HA's status, the "retained" messages already published by Vedetta: they are needed to clean up what
        # is no longer shared (e.g. devices published before the sharing choice).
        client.subscribe([(HA_STATUS_TOPIC, 0), (SCAN_TOPIC, 0), (DISCOVERY_PREFIX + "/device/+/config", 0), ("vedetta/dev/#", 0)])
        logger.info("MQTT: connesso")
        self._call(self._resync)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None) -> None:
        self.connected = False
        if getattr(reason_code, "is_failure", False):
            self.last_error = str(reason_code)
            logger.warning("MQTT: disconnesso: %s", reason_code)

    def _on_message(self, client, userdata, msg) -> None:
        payload = msg.payload.decode("utf-8", "replace").strip()
        if msg.topic == HA_STATUS_TOPIC and payload == "online":
            self._call(self._resync)  # HA has restarted: republish the discovery
        elif msg.topic == SCAN_TOPIC and payload == "PRESS" and not msg.retain:
            self._call(self._scan)
        elif msg.retain and payload and (msg.topic.startswith("vedetta/dev/") or (
                msg.topic.startswith(DISCOVERY_PREFIX + "/device/vedetta_") and msg.topic.endswith("/config"))):
            self._call(lambda t=msg.topic, p=payload: self._adopt(t, p))

    def _call(self, fn) -> None:
        loop = self._loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(fn)

    # ---- in the asyncio loop ----
    def _scan(self) -> None:
        """Equivalent to POST /api/refresh."""
        if self._state is not None:
            self._state.trigger(reason="mqtt")

    def _adopt(self, topic: str, payload: str) -> None:
        self.sync.adopt(topic, payload)
        if self._adopt_timer is not None:
            self._adopt_timer.cancel()
        # once the burst is over (retained messages all arrive together) the differences are published only once
        self._adopt_timer = self._loop.call_later(2.0, self._publish_changes) if self._loop else None

    def refresh(self) -> None:
        """After a sharing change: republish the differences right away (from any thread/context)."""
        self._call(self._publish_changes)

    def _resync(self) -> None:
        self.sync.reset()
        self._publish_changes()

    def _publish_changes(self) -> None:
        client = self.client
        if client is None or not self.connected or self._state is None:
            return
        try:
            from . import ha_data
            devices = dict(self._state.devices)
            cfg = ha_data.config_map()
            kinds = {did: ha_data.effective_type(d, cfg.get(did)) for did, d in devices.items()}
            shared = {did for did, c in cfg.items() if c.get("ha_share")}
            desired = build_desired(devices, kinds, self._new_count, self._latency_seen, shared)
            for topic, payload in self.sync.diff(desired):
                client.publish(topic, payload, qos=1, retain=True)
        except Exception:
            logger.exception("MQTT: pubblicazione fallita")

    async def _run(self) -> None:
        state = self._state
        queue = state.subscribe()
        try:
            while True:
                if not state.is_subscribed(queue):  # disconnected because it was slow: restart
                    queue = state.subscribe()
                    event: dict | None = None
                else:
                    try:
                        event = await asyncio.wait_for(queue.get(), PERIODIC_SECONDS)
                    except asyncio.TimeoutError:
                        event = None  # periodic round: update the counters
                if event is not None:
                    if event.get("type") not in WATCHED_EVENTS:
                        continue
                    await asyncio.sleep(0.5)  # group bursts of events
                    while not queue.empty():
                        extra = queue.get_nowait()
                        if extra.get("type") == "new_devices":
                            event = extra
                    if event.get("type") == "new_devices":
                        self._new_count = int(event.get("count") or 0)
                self._publish_changes()
        except asyncio.CancelledError:
            pass
        finally:
            state.unsubscribe(queue)

    # ---- state for the APIs (without password) ----
    def status(self) -> dict:
        stored = settings.mqtt_load()
        cfg = self.cfg or resolve_config(stored, os.environ)
        return {
            "active": bool(self.client),
            "connected": self.connected,
            "source": cfg["source"] if cfg else None,
            "last_error": self.last_error,
            "enabled": bool(stored.get("mqtt_enabled")),
            "host": cfg["host"] if cfg else stored.get("mqtt_host", ""),
            "port": cfg["port"] if cfg else stored.get("mqtt_port", 1883),
            "user": cfg["user"] if cfg else stored.get("mqtt_user", ""),
            "password_set": bool(cfg["password"] if cfg else stored.get("mqtt_password")),
            "published_topics": len(self.sync._sent),
        }


service = MqttService()
