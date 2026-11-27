# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The Sentinel's way out to Home Assistant (app/ha/ha_notify.py, app/ha/notify_queue.py): an event on the bus for every message, and
one notification per cycle to the recipients in their order, each after its wait, whether the one before took it or not, in the
language of Home Assistant; the settings of the Sentinel are keys apart (never in /api/settings), a wrong order is refused and the
single service of 0.99.x becomes an order of one; a refusal of Home Assistant is kept for the page and reported to the test buttons.
A fake Home Assistant answers on the WebSocket.
    python tests/check_ha_notify.py"""
import asyncio
import json
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import i18n  # noqa: E402
from app.ha import ha_notify, ha_registry, notify_queue  # noqa: E402
from app.storage import settings  # noqa: E402

DOWN = {"kind": "down", "card": "nas", "params": {"label": "NAS", "ip": "10.0.0.5"}}
BACK = {"kind": "back", "card": "nas", "params": {"label": "NAS", "ip": "10.0.0.5", "away_s": 1250}}
NEW = {"kind": "new", "card": "aa:bb", "params": {"label": "Pixel", "ip": "10.0.0.9"}}

# 1) pure: lines in the language asked, the data of the events, the commands of one cycle
assert ha_notify.lines([DOWN, BACK], "it") == ["NAS (10.0.0.5) non risponde", "NAS (10.0.0.5) è tornato dopo 21 min"]
assert ha_notify.lines([NEW], "en") == ["New device on the network: Pixel (10.0.0.9)"]
assert ha_notify.event_data(BACK) == {"card": "nas", "label": "NAS", "ip": "10.0.0.5", "minutes": 21,
                                      "brand": None, "type": None, "kind": None, "reason": None}      # 1.0.3: the device facts always there, null when not known
cmds = ha_notify.commands([NEW, DOWN], True, "notify.mobile_app_pixel", "en")
assert [c["type"] for c in cmds] == ["fire_event", "fire_event", "call_service"]
assert [c.get("event_type") for c in cmds[:2]] == ["vedetta_new_device", "vedetta_device_down"]
assert cmds[2]["domain"] == "notify" and cmds[2]["service"] == "mobile_app_pixel"
assert cmds[2]["service_data"]["message"] == "New device on the network: Pixel (10.0.0.9)\nNAS (10.0.0.5) is not answering"
assert ha_notify.commands([DOWN], False, "", "en") == []                          # both off: nothing
assert [c["type"] for c in ha_notify.commands([DOWN], True, "", "en")] == ["fire_event"]

# 2) the settings of the Sentinel: apart from the general ones, validated, kept across other saves
assert settings.sentinel_load() == {"ha_events": False, "notify_service": "", "notify_order": []}     # 19/11 decision A: nothing written to Home Assistant until the person turns it on
assert "notify_service" not in settings.load() and "notify_order" not in settings.load()
PIXEL = [{"service": "notify.mobile_app_pixel", "delay_s": 0}]
assert settings.sentinel_update({"notify_service": "notify.mobile_app_pixel"})["notify_order"] == PIXEL      # a page of 0.99.x: an order of one
settings.update({"poll_interval": 60})                                            # another save keeps it
settings.mqtt_update({"mqtt_host": "10.0.0.2"})
assert settings.sentinel_load() == {"ha_events": False, "notify_service": "", "notify_order": PIXEL}
for bad in ("light.kitchen", "notify.", "notify.Bad Name", 5, None, "notify.x; rm"):
    try:
        settings.sentinel_update({"notify_service": bad})
        raise AssertionError(f"accepted {bad!r}")
    except ValueError:
        pass
ORDER = [{"service": "notify.mobile_app_pixel", "delay_s": 0}, {"service": "notify.tv", "delay_s": 30}, {"service": "notify.tablet", "delay_s": 120}]
for bad in ([{"service": "notify.tv", "delay_s": 7}], [{"service": "light.x", "delay_s": 0}], [{"service": "notify.tv", "delay_s": 0}] * 2,
            [{"service": "notify.tv", "delay_s": 0, "x": 1}], [{"service": "notify.tv", "delay_s": True}], "notify.tv",
            [{"service": f"notify.n{i}", "delay_s": 0} for i in range(settings.NOTIFY_MAX + 1)]):
    try:
        settings.sentinel_update({"notify_order": bad})
        raise AssertionError(f"accepted {bad!r}")
    except ValueError:
        pass
assert settings.sentinel_load()["notify_order"] == PIXEL
assert settings.sentinel_update({"notify_order": ORDER})["notify_order"] == ORDER
assert settings.sentinel_load()["notify_order"] == ORDER
assert '"notify_service"' not in settings.SETTINGS_PATH.read_text(encoding="utf-8")
# a file of 0.99.x with the single service: read as an order of one
raw = json.loads(settings.SETTINGS_PATH.read_text(encoding="utf-8"))
raw.pop("notify_order")
raw["notify_service"] = "notify.tv"
settings.SETTINGS_PATH.write_text(json.dumps(raw), encoding="utf-8")
assert settings.sentinel_load()["notify_order"] == [{"service": "notify.tv", "delay_s": 0}]
settings.sentinel_update({"notify_order": ORDER})
assert notify_queue.steps(ORDER) == [(0, "notify.mobile_app_pixel"), (30, "notify.tv"), (120, "notify.tablet")]
assert ha_notify.services_of({"result": {"notify": {"mobile_app_pixel": {}, "persistent_notification": {}, "Bad Name": {}}, "light": {"x": {}}}}) == [
    "notify.mobile_app_pixel", "notify.persistent_notification"]


# 3) a fake Home Assistant on the WebSocket: what reaches it, and a refusal
class FakeWS:
    def __init__(self, refuse=None):
        self.sent, self.refuse = [], refuse
        self.queue = [{"type": "auth_required"}]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def send(self, text):
        msg = json.loads(text)
        self.sent.append(msg)
        if msg.get("type") == "auth":
            self.queue.append({"type": "auth_ok"})
            return
        self.queue.append({"type": "event", "event": {}})                         # noise in between, to be skipped
        ok = msg.get("type") != self.refuse
        self.queue.append({"id": msg["id"], "type": "result", "success": ok, "error": None if ok else {"code": "not_found", "message": "Service not found"}})

    async def recv(self):
        return json.dumps(self.queue.pop(0))


fake = {}


def connect(url, **kw):
    fake["ws"] = FakeWS(fake.get("refuse"))
    return fake["ws"]


import websockets  # noqa: E402
websockets.connect = connect
os.environ["SUPERVISOR_TOKEN"] = "t"
i18n.set_system_language("de")


received, waits = [], []                                   # every message that reaches HA, in order; the waits of the queue


def connect_all(url, **kw):
    ws = connect(url, **kw)
    received.append(ws.sent)
    return ws


websockets.connect = connect_all
real_sleep = asyncio.sleep


async def no_wait(s):
    waits.append(s)
    await real_sleep(0)
notify_queue.asyncio.sleep = no_wait


def flat():
    return [m for sent in received for m in sent if m["type"] != "auth"]


async def drained():
    while notify_queue._worker or ha_notify._tasks:
        await real_sleep(0.01)


async def run():
    ha_notify.sender([DOWN])                                                       # events off by default: only the notifications
    await drained()
    assert [m["type"] for m in flat()] == ["call_service"] * 3, flat()
    received.clear()
    waits.clear()
    settings.sentinel_update({"ha_events": True})                                  # the person turns the events on
    ha_notify.sender([DOWN])
    await drained()
    sent = flat()
    assert [m["type"] for m in sent] == ["fire_event", "call_service", "call_service", "call_service"], sent
    assert [m.get("service") for m in sent[1:]] == ["mobile_app_pixel", "tv", "tablet"], "the recipients in their order"
    assert sent[1]["service_data"] == {"title": "Vedetta", "message": "NAS (10.0.0.5) antwortet nicht"}       # the language of HA
    assert waits == [0, 30, 120], waits
    assert notify_queue.status()["waiting"] == 0 and all(v["ok"] for v in notify_queue.status()["last"].values())
    # a recipient that refuses: the ones after it still get the message; its answer is kept for the page
    received.clear()
    fake["refuse"] = "call_service"
    ha_notify.sender([DOWN, BACK])
    ha_notify.sender([NEW])                                                        # a second message waits for the first one
    await drained()
    calls = [m for m in flat() if m["type"] == "call_service"]
    assert [m["service"] for m in calls] == ["mobile_app_pixel", "tv", "tablet"] * 2, "everybody, message after message"
    assert "NAS" in calls[0]["service_data"]["message"] and "Pixel" in calls[3]["service_data"]["message"], "the first message first"
    last = notify_queue.status()["last"]
    assert last["notify.tv"]["ok"] is False and "not_found" in last["notify.tv"]["error"], last
    # the tests: «Try» on one row at once; «Send a test» = the event at once and the message in line for the whole order
    result = await ha_notify.test("notify.other")
    assert result["ok"] is False and "not_found" in result["error"], result
    fake["refuse"] = None
    assert await ha_notify.test("notify.other") == {"ok": True}
    assert flat()[-1]["service"] == "other" and notify_queue.status()["last"]["notify.other"]["ok"] is True
    received.clear()
    settings.sentinel_update({"ha_events": False})        # events off: «Send a test» writes no event either, only the messages (19/11 review)
    result = await ha_notify.test()
    await drained()
    assert result == {"ok": True, "queued": 3} and not [m for m in flat() if m["type"] == "fire_event"], (result, flat())
    received.clear()
    settings.sentinel_update({"ha_events": True})
    fake["refuse"] = "fire_event"                                                 # the event refused: the notifications still go
    result = await ha_notify.test()
    assert result["ok"] is False and "fire_event" in result["error"] and result["queued"] == 3, result
    await drained()
    assert [m.get("service") for m in flat() if m["type"] == "call_service"] == ["mobile_app_pixel", "tv", "tablet"]
    fake["refuse"] = None
    os.environ.pop("SUPERVISOR_TOKEN")
    assert await ha_notify.test() == {"ok": False, "error": "no_home_assistant"}
    ha_notify.sender([DOWN])                                                       # outside HA: nothing, no error
    assert not ha_notify._tasks and not notify_queue._worker

asyncio.run(run())


# 18/11 review: a worker that has just finished stays in _worker until its done-callback runs; a message put in that moment must not wait
# for the next alert (hours later): a finished worker counts as none.
async def finished_worker():
    notify_queue.reset()
    got = []

    async def send(service, message):
        got.append((service, message))
    done = asyncio.get_running_loop().create_future()
    done.set_result(None)
    notify_queue._worker.add(done)
    notify_queue.put("down", [{"service": "notify.phone", "delay_s": 0}], send)
    for _ in range(20):
        await asyncio.sleep(0)
    notify_queue._worker.discard(done)
    assert got == [("notify.phone", "down")], got

asyncio.run(finished_worker())


# 18/11 review: Home Assistant does not answer the first event in time: the other commands (the phone notification) still go, and the
# send reports the slow one as a refusal
class SlowFirst(FakeWS):
    async def send(self, text):
        msg = json.loads(text)
        if msg.get("id") == 1:
            self.sent.append(msg)              # no answer for the first command
            return
        await FakeWS.send(self, text)

    async def recv(self):
        while not self.queue:
            await real_sleep(0.01)
        return json.dumps(self.queue.pop(0))


async def slow_first():
    ws = SlowFirst()
    os.environ["SUPERVISOR_TOKEN"] = "t"
    websockets.connect = lambda url, **kw: ws
    saved, ha_registry.TIMEOUT_S = ha_registry.TIMEOUT_S, 0.2
    try:
        cmds = [{"type": "fire_event", "event_type": "vedetta_device_down", "event_data": {}},
                {"type": "call_service", "domain": "notify", "service": "phone", "service_data": {"message": "x"}}]
        try:
            await ha_notify.send(cmds)
            raise AssertionError("the slow command is not reported")
        except RuntimeError as exc:
            assert "no answer" in str(exc), exc
        assert [m.get("type") for m in ws.sent] == ["auth", "fire_event", "call_service"], ws.sent
    finally:
        ha_registry.TIMEOUT_S = saved
        websockets.connect = connect_all

asyncio.run(slow_first())
print("check_ha_notify: ok")
