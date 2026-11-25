"""The fine device type ("kind", an id of data/device_kinds.json) next to the category ("type") in the MQTT attributes sent to Home Assistant:
- ha_data.effective_kind: the best type inside the category that counts (the one chosen by hand wins), None when no type of it scored;
- build_desired with the fine types: the attributes gain "kind" (null when there is none) and NOTHING else changes, byte for byte
  (config, state, latency, hub; the other attributes): automations read "type" and the entities as they are;
- MqttService._publish_changes passes the fine type of the shared cards.
    python tools/run_test.py check_mqtt_kind.py"""
import json
import os
import sys
import tempfile
import types

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import ha_data, mqtt_ha, mqtt_payloads  # noqa: E402

AP = {"id": "ap1", "name": "Office Access Point", "ip": "192.0.2.10", "mac": "02:00:00:00:00:10", "online": True, "latency_ms": 4}
TV = {"id": "tv1", "name": "Living Room TV", "ip": "192.0.2.11", "mac": "02:00:00:00:00:11", "online": False, "last_seen": 1700000000.0}
ODD = {"id": "x1", "name": "xyz", "ip": "192.0.2.12", "online": True}

# 1) the fine type, inside the category that counts
assert ha_data.effective_type(AP) == "router" and ha_data.effective_kind(AP) == "accesspoint"
assert ha_data.effective_type(TV) == "media" and ha_data.effective_kind(TV) == "tv"
assert ha_data.effective_kind(ODD) is None, "nothing scored: no fine type"
groups = {kd["id"]: kd["group"] for kd in ha_data._kinds()}
hand = ha_data.effective_kind(TV, {"type_user": "pc"})
assert hand is None or groups[hand] == "pc", ("a category chosen by hand is never contradicted by the fine type", hand)
assert ha_data.effective_kind(TV, {"type_user": "generic"}) is None
assert ha_data.effective_kind(TV, None, "media") == "tv", "the category already worked out can be passed in"

# 2) the payloads: "kind" added, everything else identical
DEVS = {"ap1": AP, "tv1": TV, "x1": ODD}
TYPES = {did: ha_data.effective_type(d) for did, d in DEVS.items()}
FINE = {did: ha_data.effective_kind(d) for did, d in DEVS.items()}
before = mqtt_ha.build_desired(DEVS, TYPES, 1, set())
after = mqtt_ha.build_desired(DEVS, TYPES, 1, set(), None, FINE)
assert list(before) == list(after), "the same topics, in the same order"
for topic, payload in before.items():
    if not topic.endswith("/attrs"):
        assert after[topic] == payload, ("unchanged payload", topic)
        continue
    old, new = json.loads(payload), json.loads(after[topic])
    did = topic.split("/")[2]
    assert new.pop("kind") == FINE[did] and old.pop("kind") is None, topic
    assert new == old, ("the other attributes stay exactly as they were", topic)
    assert set(old) == {"ip", "mac", "brand", "type", "latency_ms", "last_seen", "source_type"}, ("the keys of 1.0.2, all kept", topic)
    assert old["type"] == TYPES[did]
assert json.loads(before[mqtt_ha.device_topics("ap1")["attrs"]])["kind"] is None, "without fine types: kind is null, never absent"
assert '"kind":"accesspoint"' in after[mqtt_ha.device_topics("ap1")["attrs"]]
assert '"kind":null' in after[mqtt_ha.device_topics("x1")["attrs"]]
assert json.loads(after[mqtt_ha.device_topics("ap1")["config"]])["dev"]["model"] == "router", "the device model stays the category"

# 3) the service passes the fine type of the shared cards (the category chosen by hand respected)
ha_data.config_map = lambda: {"ap1": {"ha_share": True}, "tv1": {"ha_share": True, "type_user": "pc"}}
svc = mqtt_ha.MqttService()
published = []
svc.client = types.SimpleNamespace(publish=lambda topic, payload, **kw: published.append((topic, payload)))
svc.connected = True
svc._state = types.SimpleNamespace(devices=DEVS)
svc._publish_changes()
sent = dict(published)
ap_attrs = json.loads(sent[mqtt_ha.device_topics("ap1")["attrs"]])
tv_attrs = json.loads(sent[mqtt_ha.device_topics("tv1")["attrs"]])
assert (ap_attrs["type"], ap_attrs["kind"]) == ("router", "accesspoint"), ap_attrs
assert tv_attrs["type"] == "pc" and (tv_attrs["kind"] is None or groups[tv_attrs["kind"]] == "pc"), tv_attrs
assert mqtt_ha.device_topics("x1")["attrs"] not in sent, "a card not shared is not published"
assert mqtt_payloads.build_desired is mqtt_ha.build_desired
print("ok: kind next to type in the MQTT attributes")
