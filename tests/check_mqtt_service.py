"""Reference test of the MQTT service (ha/mqtt_ha.py MqttService) with a fake paho client: it connects with the right options, announces itself
online, subscribes to the topics it needs, reacts to Home Assistant restarting / the scan button / retained leftovers, publishes only the
differences (configs first, retained, QoS 1), stays silent while disconnected, follows the device events, and closes cleanly."""
import asyncio
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
made = []


class FakeClient:
    fail_connect_next = False

    def __init__(self, api, client_id=None):
        self.client_id, self.calls = client_id, []
        self.fail_connect = FakeClient.fail_connect_next
        made.append(self)

    def __getattr__(self, name):
        def call(*a, **k):
            self.calls.append((name, a, k))
            if name == "connect_async" and self.fail_connect:
                raise OSError("unreachable")
            return types.SimpleNamespace(wait_for_publish=lambda t=None: None)
        return call

    def names(self):
        return [c[0] for c in self.calls]


paho = types.ModuleType("paho")
mq = types.ModuleType("paho.mqtt")
cl = types.ModuleType("paho.mqtt.client")
cl.Client, cl.CallbackAPIVersion = FakeClient, types.SimpleNamespace(VERSION2=2)
mq.client, paho.mqtt = cl, mq
sys.modules.update({"paho": paho, "paho.mqtt": mq, "paho.mqtt.client": cl})

from app.ha import ha_data, mqtt_ha, mqtt_config, mqtt_payloads  # noqa: E402
from app.storage import settings  # noqa: E402

CFG = {"host": "broker", "port": 1883, "user": "u", "password": "p", "source": "test"}
mqtt_ha.resolve_config = lambda stored, env: CFG
mqtt_config.resolve_config = mqtt_ha.resolve_config
settings.mqtt_load = lambda: {"mqtt_enabled": True}


class FakeState:
    def __init__(self):
        self.devices, self.triggered, self.q, self.subscribed = {"d1": {"id": "d1"}}, [], None, None
        self._new = types.SimpleNamespace(macs=frozenset({"a", "b"}))
        self.events = []        # what the service tells the open pages (the link with the broker)

    def emit_event(self, event):
        self.events.append(event)

    def subscribe(self):
        self.q = asyncio.Queue()
        self.subscribed = True
        return self.q

    def unsubscribe(self, q):
        self.subscribed = False

    def is_subscribed(self, q):
        return self.subscribed

    def trigger(self, reason=""):
        self.triggered.append(reason)


desired = {"vedetta/dev/d1/state": "S1", "homeassistant/device/vedetta_d1/config": "C1"}      # the state comes first on purpose
mqtt_ha.build_desired = lambda devices, kinds, new_count, latency_seen, shared: dict(desired)
mqtt_payloads.build_desired = mqtt_ha.build_desired
ha_data.config_map = lambda: {"d1": {"ha_share": "1"}}
ha_data.effective_type = lambda d, c: "generic"


async def scenario():
    svc = mqtt_ha.MqttService()
    state = FakeState()
    await svc.start(state)
    c = svc.client
    assert c is made[0] and c.client_id.startswith("vedetta-") and svc._new_count == 2
    assert c.names() == ["username_pw_set", "will_set", "reconnect_delay_set", "connect_async", "loop_start"], c.names()
    assert ("username_pw_set", ("u", "p"), {}) in c.calls
    assert c.calls[1][1][:2] == (mqtt_ha.STATUS_TOPIC, "offline"), "the last will tells HA that Vedetta is gone"
    LINK = {"type": "mqtt", "active": True, "connected": False}
    assert state.events == [LINK], ("started: the open pages learn that the link is configured and not yet connected", state.events)

    svc._on_connect(c, None, None, types.SimpleNamespace(is_failure=True))        # refused
    assert not svc.connected and svc.last_error

    def publishes():
        return [x for x in c.calls if x[0] == "publish"]

    assert publishes() == []
    svc._publish_changes()
    assert publishes() == [], "silent while disconnected"

    svc._on_connect(c, None, None, types.SimpleNamespace(is_failure=False))        # connected: online, subscriptions, full resync
    await asyncio.sleep(0.01)
    assert svc.connected and svc.last_error == ""
    assert state.events[-1] == {"type": "mqtt", "active": True, "connected": True}, "connected: the pages are told (from the network thread, through the loop)"
    sub = [x for x in c.calls if x[0] == "subscribe"][0][1][0]
    assert (mqtt_ha.SCAN_TOPIC, 0) in sub and (mqtt_ha.HA_STATUS_TOPIC, 0) in sub
    assert publishes()[0][1][:2] == (mqtt_ha.STATUS_TOPIC, "online")
    sent = [(p[1][0], p[1][1]) for p in publishes()[1:]]
    assert sent == [("homeassistant/device/vedetta_d1/config", "C1"), ("vedetta/dev/d1/state", "S1")], "configs before states"
    assert all(p[2].get("retain") is True and p[2].get("qos") == 1 for p in publishes()[1:])

    n = len(publishes())
    svc._publish_changes()
    assert len(publishes()) == n, "nothing changed: nothing published"
    desired["vedetta/dev/d1/state"] = "S2"
    svc.refresh()
    await asyncio.sleep(0.01)
    assert publishes()[-1][1][:2] == ("vedetta/dev/d1/state", "S2") and len(publishes()) == n + 1
    del desired["homeassistant/device/vedetta_d1/config"]                          # no longer shared: HA is told to remove it
    svc._publish_changes()
    assert publishes()[-1][1][:2] == ("homeassistant/device/vedetta_d1/config", "")

    def msg(topic, payload, retain=False):
        return types.SimpleNamespace(topic=topic, payload=payload.encode(), retain=retain)

    n = len(publishes())
    svc._on_message(c, None, msg(mqtt_ha.HA_STATUS_TOPIC, "online"))               # HA restarted: everything is sent again
    await asyncio.sleep(0.01)
    assert len(publishes()) > n
    svc._on_message(c, None, msg(mqtt_ha.SCAN_TOPIC, "PRESS", retain=True))        # a retained press is stale: ignored
    await asyncio.sleep(0.01)
    assert state.triggered == []
    svc._on_message(c, None, msg(mqtt_ha.SCAN_TOPIC, "PRESS"))
    await asyncio.sleep(0.01)
    assert state.triggered == ["mqtt"]
    svc._on_message(c, None, msg("vedetta/dev/old/state", "X", retain=True))        # a retained leftover is adopted (and later cleaned up)
    await asyncio.sleep(0.01)
    assert svc.sync._sent.get("vedetta/dev/old/state") == "X"
    svc._adopt_timer.cancel()
    svc._on_message(c, None, msg("somewhere/else", "x", retain=True))
    await asyncio.sleep(0.01)
    assert "somewhere/else" not in svc.sync._sent

    svc._on_disconnect(c, None, None, types.SimpleNamespace(is_failure=True))
    await asyncio.sleep(0.01)
    assert not svc.connected and svc.last_error
    assert state.events[-1] == LINK, "dropped: the pages are told, the link stays configured"
    assert all(set(e) == {"type", "active", "connected"} for e in state.events), "the event carries nothing else: never an address or a credential"
    st = svc.status()
    assert st["active"] and st["host"] == "broker" and st["password_set"] and st["enabled"] and "p" not in [str(v) for v in st.values()]

    # the loop follows the device events (and ignores the others), and restarts its subscription if it was dropped
    mqtt_ha.PERIODIC_SECONDS = 0.05
    svc.connected = True
    svc._state, state.subscribed = state, None
    desired["vedetta/dev/d1/state"] = "S3"
    task = asyncio.create_task(svc._run())
    await asyncio.sleep(0.02)
    state.q.put_nowait({"type": "poll"})
    state.q.put_nowait({"type": "new_devices", "count": 7})
    await asyncio.sleep(0.9)
    assert svc._new_count == 7 and publishes()[-1][1][:2] == ("vedetta/dev/d1/state", "S3")
    task.cancel()
    await asyncio.sleep(0.01)
    assert state.subscribed is False

    await svc.stop()
    assert state.events[-1] == {"type": "mqtt", "active": False, "connected": False}, "stopped: not configured any more"
    assert svc.client is None and "loop_stop" in c.names() and "disconnect" in c.names()
    assert any(x[0] == "publish" and x[1][:2] == (mqtt_ha.STATUS_TOPIC, "offline") for x in c.calls), "a clean stop says offline"

    # no configuration: nothing is created; a connection failure at start-up is reported, not raised
    svc2 = mqtt_ha.MqttService()
    mqtt_ha.resolve_config = lambda stored, env: None
    mqtt_config.resolve_config = mqtt_ha.resolve_config
    await svc2._apply_config()
    assert svc2.client is None
    mqtt_ha.resolve_config = lambda stored, env: CFG
    mqtt_config.resolve_config = mqtt_ha.resolve_config
    FakeClient.fail_connect_next = True
    await svc2._apply_config()
    assert "unreachable" in svc2.last_error


asyncio.new_event_loop().run_until_complete(scenario())
print("TUTTO OK")
