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
import logging
import os

from ..storage import settings
from .mqtt_config import _env_config, _port, _stored_config, resolve_config  # noqa: F401
from .mqtt_payloads import DISCOVERY_PREFIX, HUB_ID, HUB_STATE_TOPIC, SCAN_TOPIC, STATUS_TOPIC, _SLUG_RE, _add_device_entries, _fmt_time, _is_published, _j, _origin, build_desired, config_topic, device_attrs, device_config, device_topics, hub_config, hub_state, slug, version  # noqa: F401
from . import ha_data

logger = logging.getLogger("dashboard")

HA_STATUS_TOPIC = "homeassistant/status"
PERIODIC_SECONDS = 60  # counters refresh even without events
WATCHED_EVENTS = ("device", "removed", "new_devices")


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
def _is_own_retained(topic: str, retain, payload: str) -> bool:
    """A retained, non-empty message that Vedetta itself published earlier (device topics or its discovery configs)."""
    return bool(retain and payload and (topic.startswith("vedetta/dev/") or (
        topic.startswith(DISCOVERY_PREFIX + "/device/vedetta_") and topic.endswith("/config"))))


async def _next_event(state, queue):
    """Waits for the next bus event: (queue, event). A queue dropped by the state (too slow) is replaced by a fresh one and a timeout
    (the periodic round) gives no event."""
    if not state.is_subscribed(queue):  # disconnected because it was slow: restart
        return state.subscribe(), None
    try:
        return queue, await asyncio.wait_for(queue.get(), PERIODIC_SECONDS)
    except asyncio.TimeoutError:
        return queue, None  # periodic round: update the counters


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
        self._new_count = len(getattr(getattr(state, "_new", None), "macs", ()) or ())
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
        self._emit_link()
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
        self._emit_link()

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
        self._announce()
        client.publish(STATUS_TOPIC, "online", qos=1, retain=True)
        # besides the command and HA's status, the "retained" messages already published by Vedetta: they are needed to clean up what
        # is no longer shared (e.g. devices published before the sharing choice).
        client.subscribe([(HA_STATUS_TOPIC, 0), (SCAN_TOPIC, 0), (DISCOVERY_PREFIX + "/device/+/config", 0), ("vedetta/dev/#", 0)])
        logger.info("MQTT: connesso")
        self._call(self._resync)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None) -> None:
        self.connected = False
        self._announce()
        if getattr(reason_code, "is_failure", False):
            self.last_error = str(reason_code)
            logger.warning("MQTT: disconnesso: %s", reason_code)

    def _on_message(self, client, userdata, msg) -> None:
        payload = msg.payload.decode("utf-8", "replace").strip()
        if msg.topic == HA_STATUS_TOPIC and payload == "online":
            self._call(self._resync)  # HA has restarted: republish the discovery
        elif msg.topic == SCAN_TOPIC and payload == "PRESS" and not msg.retain:
            self._call(self._scan)
        elif _is_own_retained(msg.topic, msg.retain, payload):
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
            devices = dict(self._state.devices)
            cfg = ha_data.config_map()
            kinds = {did: ha_data.effective_type(d, cfg.get(did)) for did, d in devices.items()}
            shared = {did for did, c in cfg.items() if c.get("ha_share")}
            desired = build_desired(devices, kinds, self._new_count, self._latency_seen, shared)
            for topic, payload in self.sync.diff(desired):
                client.publish(topic, payload, qos=1, retain=True)
        except Exception:
            logger.exception("MQTT: pubblicazione fallita")

    async def _absorb_burst(self, queue, event: dict) -> None:
        """A watched event arrived: wait a moment, take the events that piled up, and remember the last new-devices count."""
        await asyncio.sleep(0.5)  # group bursts of events
        while not queue.empty():
            extra = queue.get_nowait()
            if extra.get("type") == "new_devices":
                event = extra
        if event.get("type") == "new_devices":
            self._new_count = int(event.get("count") or 0)

    async def _run(self) -> None:
        state = self._state
        queue = state.subscribe()
        try:
            while True:
                queue = await self._turn(queue)
        except asyncio.CancelledError:
            pass
        finally:
            state.unsubscribe(queue)

    async def _turn(self, queue):
        """One turn of the loop: wait for an event, publish what changed (a periodic round has no event and publishes too; an event that is not watched does not). Returns the queue to use next."""
        queue, event = await _next_event(self._state, queue)
        if event is not None:
            if event.get("type") not in WATCHED_EVENTS:
                return queue
            await self._absorb_burst(queue, event)
        self._publish_changes()
        return queue

    # ---- state for the APIs (without password) ----
    def link(self) -> dict:
        """The two facts the page needs (configured and running; connected to the broker): nothing else, never an address or a credential."""
        return {"active": bool(self.client), "connected": self.connected}

    def event(self) -> dict:
        return {"type": "mqtt", **self.link()}

    def _emit_link(self) -> None:
        """Tells the open pages (in the asyncio loop) that the link with the broker changed."""
        if self._state is not None:
            self._state.emit_event(self.event())

    def _announce(self) -> None:
        """The same from the network thread of paho."""
        self._call(self._emit_link)

    def status(self) -> dict:
        stored = settings.mqtt_load()
        cfg = self.cfg or resolve_config(stored, os.environ)
        return {
            **self.link(),
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
