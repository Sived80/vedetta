"""The endless loops of the service must END when they are cancelled, within a short time and after cleaning up (the shutdown of the service and a restart of a part of it depend on it).
For each of the five loops - the check cycle of the state, the network roles, the Home Assistant registry reader, the continuous Bonjour listener and the MQTT publisher - the loop is started with the
outside world replaced by fakes and cancelled in the situations where it can be: while it waits for its next turn and, where the loop calls out, while it is inside that call (a call that never returns).
Each case must be over within two seconds (a loop that did not stop would hang the test, so every wait has a limit)."""
import asyncio
import os
import sys
import tempfile
import time
import types
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()      # never the real folder of the developer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
LIMIT = 2.0
real_sleep = asyncio.sleep


async def within(coro, what):
    """Waits for `coro` at most LIMIT seconds. A coroutine that swallows the cancel that wait_for sends when the time is up would END normally after exactly LIMIT seconds and look
    punctual, so the time that really passed is checked too: finishing is not enough, it has to finish soon."""
    started = time.monotonic()
    try:
        result = await asyncio.wait_for(coro, LIMIT)
    except asyncio.TimeoutError:
        raise AssertionError("%s did not finish within %s s after the cancel" % (what, LIMIT))
    if time.monotonic() - started >= LIMIT * 0.9:
        raise AssertionError("%s needed the time limit to end: it ended only when wait_for cancelled it" % what)
    return result


async def forever(*args, **kwargs):
    await real_sleep(3600)           # a call out that never returns


async def settle():
    await real_sleep(0.05)           # lets the loop reach its wait


async def case_state_cycle():
    from app import state as state_mod
    for inside in (False, True):
        st = state_mod.DeviceState()
        polls = []

        async def poll():
            polls.append(1)
            if inside:
                await real_sleep(3600)
        st.poll_once = poll
        st.start()
        await settle()
        assert polls, "the cycle started its first turn"
        await within(st.stop(), "DeviceState.stop (%s)" % ("inside poll_once" if inside else "waiting for the next turn"))
        assert st._task.done(), "the loop of the state is over"


async def case_roles():
    from app.recognition import roles
    for inside in (False, True):
        calls = []

        async def refresh(state):
            calls.append(1)
            await real_sleep(3600)
        original_refresh, original_sleep = roles.refresh, asyncio.sleep
        roles.refresh = refresh

        async def quick(delay, *a):
            await original_sleep(min(delay, 0.01) if inside else delay)
        asyncio.sleep = quick
        try:
            roles.start(object())
            await settle()
            if inside:
                assert calls, "the loop reached its call out"
            await within(roles.stop(), "roles.stop (%s)" % ("inside refresh" if inside else "in its first wait"))
        finally:
            roles.refresh = original_refresh
            asyncio.sleep = original_sleep
        assert roles._rt.task is None, "the task of the roles is released"


async def case_ha_registry():
    from app.ha import ha_registry
    for inside in (False, True):
        calls = []

        async def refresh():
            calls.append(1)
            if inside:
                await real_sleep(3600)
        saved = (ha_registry.token, ha_registry.active, ha_registry.refresh, ha_registry._load_cache, ha_registry.REFRESH_S)
        ha_registry.token, ha_registry.active, ha_registry.refresh, ha_registry._load_cache = (lambda: "t"), (lambda: True), refresh, (lambda: None)
        ha_registry.REFRESH_S = 3600
        try:
            ha_registry.start()
            await settle()
            assert calls, "the loop reached its call"
            task = ha_registry._task
            await ha_registry.stop()
            await within(asyncio.gather(task, return_exceptions=True), "the loop of the Home Assistant registry (%s)" % ("inside refresh" if inside else "waiting"))
            assert task.done()
        finally:
            ha_registry.token, ha_registry.active, ha_registry.refresh, ha_registry._load_cache, ha_registry.REFRESH_S = saved
            ha_registry._task = None


async def case_mdns():
    log = []

    class FakeBrowser:
        def __init__(self, zc, name, handlers=None):
            log.append(("browser", name))

        async def async_cancel(self):
            log.append("browser cancelled")

    class FakeZeroconf:
        def __init__(self, ip_version=None):
            self.zeroconf = object()

        async def async_close(self):
            log.append("zeroconf closed")
    zc = types.ModuleType("zeroconf")
    zc.IPVersion = types.SimpleNamespace(V4Only="v4")
    zc.ServiceStateChange = types.SimpleNamespace(Removed="removed")
    zca = types.ModuleType("zeroconf.asyncio")
    zca.AsyncServiceBrowser, zca.AsyncServiceInfo, zca.AsyncZeroconf = FakeBrowser, object, FakeZeroconf
    saved = {k: sys.modules.get(k) for k in ("zeroconf", "zeroconf.asyncio")}
    sys.modules["zeroconf"], sys.modules["zeroconf.asyncio"] = zc, zca
    from app.scan import mdns_listener
    mdns_listener.STORE_PATH = Path(tempfile.mkdtemp()) / "mdns_seen.json"
    try:
        task = asyncio.ensure_future(mdns_listener._listen())
        await settle()
        assert ("browser", mdns_listener.mdns_parse._MDNS_META_TYPE) in log, "the listener started browsing"
        task.cancel()
        try:
            await within(task, "the Bonjour listener")
            raise AssertionError("the listener swallowed the cancel")
        except asyncio.CancelledError:
            pass
        assert "browser cancelled" in log and "zeroconf closed" in log, "the listener cleaned up before ending: %r" % (log,)
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


async def case_mqtt():
    from app.ha import mqtt_ha
    log = []

    class FakeState:
        def __init__(self):
            self.queue = asyncio.Queue()

        def subscribe(self):
            log.append("subscribed")
            return self.queue

        def is_subscribed(self, queue):
            return True

        def unsubscribe(self, queue):
            log.append("unsubscribed")
    for inside in (False, True):
        log.clear()
        svc = mqtt_ha.MqttService()
        svc._state = FakeState()
        calls = []

        def publish():
            calls.append(1)
        svc._publish_changes = publish
        if inside:                               # a burst of events: the loop is inside its short wait when the cancel arrives
            svc._state.queue.put_nowait({"type": next(iter(mqtt_ha.WATCHED_EVENTS))})
        task = asyncio.ensure_future(svc._run())
        await settle()
        task.cancel()
        await within(asyncio.gather(task, return_exceptions=True), "the MQTT publisher loop (%s)" % ("in a burst" if inside else "waiting for an event"))
        assert task.done() and "unsubscribed" in log, "the publisher left the bus when it ended: %r" % (log,)


async def main():
    for name, case in (("state cycle", case_state_cycle), ("network roles", case_roles), ("Home Assistant registry", case_ha_registry), ("Bonjour listener", case_mdns), ("MQTT publisher", case_mqtt)):
        await within(case(), "the whole case of the " + name)
        print("ends when cancelled:", name)

asyncio.new_event_loop().run_until_complete(main())
print("TUTTO OK")
