"""Golden-master test of four pieces of ha/mqtt_ha.py: resolve_config (settings + environment -> effective MQTT configuration, with the ORDER of the lookups), build_desired (devices ->
ordered "topic -> payload" map and the final `latency_seen` set), MqttService._on_message (broker message -> scheduled calls, for sequences of messages, with the service state and an event
log of the fake loop) and MqttService._run (the asyncio listener, driven with asyncio.run, a scripted fake state/queue and fake `wait_for`/`sleep`): generated inputs must give exactly the
results (stored as a sha1 digest per case plus a small readable sample) in tests/golden/mqtt_ha.json, written from the code as it was before the functions were split.
Regenerate only on purpose:  MQTTHA_GOLDEN_UPDATE=1 python tests/check_mqtt_ha_golden.py"""
import asyncio
import hashlib
import json
import os
import random
import sys
import types
from pathlib import Path

os.environ["VEDETTA_VERSION"] = "9.9.9"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import mqtt_ha, mqtt_payloads  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "mqtt_ha.json"
rng = random.Random(135711)
mqtt_ha._fmt_time = lambda ts: None if not ts else "T%s" % ts
mqtt_payloads._fmt_time = mqtt_ha._fmt_time
STATS: dict = {}


def pick(seq):
    return seq[rng.randrange(len(seq))]


def dig(obj) -> str:
    return hashlib.sha1(json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def count(key, cond):
    STATS[key] = STATS.get(key, 0) + (1 if cond else 0)


# ---------------- resolve_config ----------------
class LogDict(dict):
    def __init__(self, data, log, tag):
        super().__init__(data)
        self.log, self.tag = log, tag

    def get(self, key, default=None):
        self.log.append([self.tag, key])
        return super().get(key, default)


HOSTS = [None, "", " ", "  \t", "broker", "Broker.LAN", "  broker.lan ", 5]
PORTS = [None, "", "abc", "0", "1", "65535", "65536", " 8883 ", "-5", "1883", 1884, 70000, "12.5"]
USERS = [None, "", "u1", "stored_u"]
PASSES = [None, "", "p1", "stored_p"]


def case_resolve():
    env, stored = {}, {}
    for key, vals in (("VEDETTA_MQTT_HOST", HOSTS), ("VEDETTA_MQTT_PORT", PORTS), ("VEDETTA_MQTT_USER", USERS), ("VEDETTA_MQTT_PASSWORD", PASSES)):
        if rng.random() < 0.8:
            env[key] = pick(vals)
    if rng.random() < 0.85:
        stored["mqtt_enabled"] = pick([True, False, None, 0, 1, ""])
    if rng.random() < 0.85:
        stored["mqtt_host"] = pick(["", None, "stored.lan", " sp "])
    if rng.random() < 0.8:
        stored["mqtt_port"] = pick(PORTS)
    if rng.random() < 0.7:
        stored["mqtt_user"] = pick(USERS)
    if rng.random() < 0.7:
        stored["mqtt_password"] = pick(PASSES)
    log: list = []
    try:
        res = mqtt_ha.resolve_config(LogDict(stored, log, "s"), LogDict(env, log, "e"))
    except Exception as exc:
        res = "EXC " + type(exc).__name__
    count("resolve_none", res is None)
    count("resolve_env", isinstance(res, dict) and res["source"] == "env")
    count("resolve_set", isinstance(res, dict) and res["source"] == "settings")
    count("resolve_exc", isinstance(res, str))
    return {"res": res, "log": log}


# ---------------- build_desired ----------------
IDS = ["d1", "D2", "dev 3", "a/b#c", "x", "mac-aa:bb", "ünï", "___", "", "d1x", "dev_4", "5"]
NAMES = [None, "", "TV", "Café"]
BRANDS = [None, "", "Acme", "B"]


def make_dev(did):
    dev = {}
    if rng.random() < 0.93:
        dev["id"] = pick([did, did, did, "other-" + did])
    for key, vals in (("name", NAMES), ("ip", [None, "10.0.0.%d" % rng.randrange(1, 40)]), ("mac", [None, "aa:bb:cc:00:00:01"]), ("brand", BRANDS), ("vendor", BRANDS),
                      ("latency_ms", [None, None, 0, 5, 12.5, 40]), ("online", [True, False, None, 1, 0]), ("is_mobile", [True, False, None]),
                      ("last_seen", [None, 0, 1_700_000_000, 1_700_000_500.5])):
        if rng.random() < 0.85:
            dev[key] = pick(vals)
    return dev


def case_build():
    ids = rng.sample(IDS, rng.randrange(0, 7))
    devices = {d: make_dev(d) for d in ids}
    kinds = {d: pick([None, "", "tv", "phone"]) for d in ids if rng.random() < 0.7}
    kinds["zz"] = "ghost"
    seen = {d for d in IDS + ["gone1", "gone2"] if rng.random() < 0.3}
    shared = None if rng.random() < 0.3 else (set() if rng.random() < 0.1 else {d for d in IDS + ["gone1"] if rng.random() < 0.6})
    new_count = pick([0, 0, 1, 3, 7])
    try:
        out = mqtt_ha.build_desired(devices, kinds, new_count, seen, shared)
        res = {"out": list(out.items())}
    except Exception as exc:
        res = {"exc": type(exc).__name__}
    res["seen"] = sorted(seen)
    count("build_exc", "exc" in res)
    count("build_lat", any("/latency" in t for t, _ in res.get("out", [])))
    count("build_many", len(res.get("out", [])) > 8)
    return res


# ---------------- _on_message ----------------
class FakeLoop:
    def __init__(self, log):
        self.log = log

    def is_closed(self):
        return False

    def call_soon_threadsafe(self, fn):
        self.log.append(["soon"])
        fn()

    def call_later(self, delay, fn):
        self.log.append(["later", delay, getattr(fn, "__name__", "?")])
        return FakeTimer(self.log)


class FakeTimer:
    def __init__(self, log):
        self.log = log

    def cancel(self):
        self.log.append(["cancel"])


class ClosedLoop(FakeLoop):
    def is_closed(self):
        return True


class FakeSt:
    def __init__(self, log):
        self.log = log

    def trigger(self, reason=None):
        self.log.append(["trigger", reason])


TOPICS = [mqtt_ha.HA_STATUS_TOPIC, mqtt_ha.SCAN_TOPIC, "vedetta/dev/x/state", "vedetta/dev/", "vedetta/devx", "homeassistant/device/vedetta_x/config",
          "homeassistant/device/vedetta_x/state", "homeassistant/device/other/config", "homeassistant/device/vedetta_/config", "homeassistant/status/x", "vedetta/hub/scan/set2", "other"]
PAYLOADS = [b"online", b"ONLINE", b"Online", b"online", b" online\n", b"offline", b"PRESS", b"press", b"PRESS ", b"", b"  ", b"\xff\xfe", b"{}", b"x"]


def case_on_message():
    log: list = []
    svc = mqtt_ha.MqttService()
    kind = rng.random()
    svc._loop = None if kind < 0.1 else (ClosedLoop(log) if kind < 0.2 else FakeLoop(log))
    svc._state = None if rng.random() < 0.15 else FakeSt(log)
    svc._publish_changes = lambda: log.append(["publish"])
    if rng.random() < 0.4:
        svc._adopt_timer = FakeTimer(log)
    if rng.random() < 0.4:
        svc.sync._sent["homeassistant/device/vedetta_old/config"] = "old"
    for _ in range(rng.randrange(1, 6)):
        msg = types.SimpleNamespace(topic=pick(TOPICS), payload=pick(PAYLOADS), retain=pick([True, False, 0, 1]))
        log.append(["msg", msg.topic, msg.payload.decode("utf-8", "replace"), msg.retain])
        try:
            svc._on_message(None, None, msg)
        except Exception as exc:
            log.append(["EXC", type(exc).__name__])
    kinds = [e[0] for e in log]
    for k in ("later", "cancel", "trigger", "publish", "soon"):
        count("msg_" + k, k in kinds)
    return {"log": log, "sent": sorted(svc.sync._sent.items()), "timer": type(svc._adopt_timer).__name__}


# ---------------- _run ----------------
class FakeQueue:
    def __init__(self, name):
        self.name, self.items = name, []

    async def get(self):
        return None

    def empty(self):
        return not self.items

    def get_nowait(self):
        return self.items.pop(0)


class RunState:
    def __init__(self, log, unsub_flags):
        self.log, self.flags, self.n, self.queue = log, list(unsub_flags), 0, None

    def subscribe(self):
        self.queue = FakeQueue("q%d" % self.n)
        self.n += 1
        self.log.append(["subscribe", self.queue.name])
        return self.queue

    def is_subscribed(self, q):
        if len(self.log) > 400:  # safety: a broken loop must end the test, not hang it
            raise asyncio.CancelledError()
        r = not (self.flags.pop(0) if self.flags else False)
        self.log.append(["is_subscribed", q.name, r])
        return r

    def unsubscribe(self, q):
        self.log.append(["unsubscribe", q.name])


def run_case():
    log: list = []
    steps, extras = [], []
    for _ in range(rng.randrange(1, 8)):
        if rng.random() < 0.2:
            steps.append(("timeout",))
        else:
            t = pick(["device", "removed", "new_devices", "new_devices", "other", None, "device"])
            ev = {} if t is None else {"type": t}
            if t == "new_devices" and rng.random() < 0.9:
                ev["count"] = pick([0, 2, 5, None, "4", "", "x"])
            steps.append(("ev", ev))
        extras.append([pick([{"type": "new_devices", "count": pick([1, 9, None, "6", "zz"])}, {"type": "device"}, {"type": "new_devices", "count": 0}, {}])
                       for _ in range(rng.choice([0, 0, 1, 2, 3]))])
    st = RunState(log, [rng.random() < 0.15 for _ in range(12)])
    svc = mqtt_ha.MqttService()
    svc._state = st
    svc._new_count = pick([0, 3])
    svc._publish_changes = lambda: log.append(["publish", svc._new_count])

    async def wait_for(coro, timeout):
        coro.close()
        log.append(["wait_for", timeout])
        if not steps:
            raise asyncio.CancelledError()
        step = steps.pop(0)
        if step[0] == "timeout":
            raise asyncio.TimeoutError()
        return step[1]

    async def sleep(delay):
        log.append(["sleep", delay])
        if extras:
            st.queue.items.extend(extras.pop(0))

    old = mqtt_ha.asyncio
    mqtt_ha.asyncio = types.SimpleNamespace(wait_for=wait_for, sleep=sleep, TimeoutError=asyncio.TimeoutError, CancelledError=asyncio.CancelledError)
    try:
        asyncio.run(svc._run())
        exc = None
    except BaseException as e:
        exc = type(e).__name__
    finally:
        mqtt_ha.asyncio = old
    kinds = [e[0] for e in log]
    for k in ("sleep", "publish", "subscribe", "unsubscribe"):
        count("run_" + k, k in kinds)
    count("run_sub2", kinds.count("subscribe") > 1)
    count("run_new", svc._new_count not in (0, 3))
    count("run_exc", exc is not None)
    return {"log": log, "exc": exc, "new": svc._new_count, "left": len(steps)}


def main():
    res, samples = {}, {}
    for name, fn, n in (("resolve", case_resolve, 2500), ("build", case_build, 1500), ("msg", case_on_message, 2500), ("run", run_case, 2500)):
        res[name], samples[name] = [], []
        for i in range(n):
            r = fn()
            res[name].append(dig(r))
            if i < 4:
                samples[name].append(r)
    return {"digests": res, "samples": samples}


out = json.loads(json.dumps(main(), ensure_ascii=False))
if os.environ.get("MQTTHA_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(out, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
for part in ("resolve", "build", "msg", "run"):
    a, b = out["digests"][part], want["digests"][part]
    assert len(a) == len(b), part
    for i, (x, y) in enumerate(zip(a, b)):
        assert x == y, "%s case %d differs" % (part, i)
assert out["samples"] == want["samples"]
s = STATS
assert s["resolve_none"] > 100 and s["resolve_env"] > 300 and s["resolve_set"] > 100 and s["resolve_exc"] > 20, s
assert s["build_exc"] > 20 and s["build_lat"] > 400 and s["build_many"] > 200, s
for k in ("later", "cancel", "trigger", "publish", "soon"):
    assert s["msg_" + k] > 20, s
for k in ("sleep", "publish", "subscribe", "unsubscribe"):
    assert s["run_" + k] > 100, s
assert s["run_sub2"] > 100 and s["run_new"] > 100 and s["run_exc"] > 5, s
print("TUTTO OK")
