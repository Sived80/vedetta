"""The loop of the MQTT service that follows the event bus (MqttService._run), with a fake state: a watched event is followed by one publication (after a moment, to group a burst), an event that is not
watched gives none, a burst keeps the last count of new devices, the periodic round (no event) publishes, a queue that the state dropped is replaced by a fresh one, and a cancel ends the loop quietly after the
last queue was released. Written on the code before it was flattened and kept passing after it (differential proof)."""
import asyncio
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import mqtt_ha  # noqa: E402


class FakeState:
    def __init__(self):
        self.queues, self.alive, self.released = [], set(), []

    def subscribe(self):
        if len(self.queues) > 50:
            raise RuntimeError("runaway: the loop subscribes again and again without waiting")      # a loop that never waits must fail here, not fill the memory
        q = asyncio.Queue()
        self.queues.append(q)
        self.alive.add(q)
        return q

    def is_subscribed(self, q):
        return q in self.alive

    def unsubscribe(self, q):
        self.released.append(q)
        self.alive.discard(q)


def build(periodic=30):
    mqtt_ha.PERIODIC_SECONDS = periodic
    state, service, published = FakeState(), mqtt_ha.MqttService(), []
    service._state = state
    service._publish_changes = lambda: published.append(1)
    service._new_count = 0
    return state, service, published


async def settle(seconds=0.8):
    await asyncio.sleep(seconds)          # the service waits half a second to group a burst


async def case_watched_and_unwatched():
    state, service, published = build()
    task = asyncio.create_task(service._run())
    await asyncio.sleep(0.05)
    state.queues[0].put_nowait({"type": "presence"})       # not watched
    await settle()                                          # longer than the half second a watched event waits to group a burst
    assert published == [], "an event that is not watched gives no publication"
    state.queues[0].put_nowait({"type": "device"})
    await settle()
    assert published == [1], published
    task.cancel()
    assert await task is None, "a cancel ends the loop quietly"
    assert state.released == [state.queues[0]]


async def case_burst_keeps_last_count():
    state, service, published = build()
    task = asyncio.create_task(service._run())
    await asyncio.sleep(0.05)
    q = state.queues[0]
    q.put_nowait({"type": "new_devices", "count": 2})
    q.put_nowait({"type": "device"})
    q.put_nowait({"type": "new_devices", "count": 5})
    q.put_nowait({"type": "removed"})
    await settle()
    assert published == [1], "a burst is one publication: %s" % published
    assert service._new_count == 5, service._new_count
    # a first event that is a count and nothing after it
    q.put_nowait({"type": "new_devices", "count": 1})
    await settle()
    assert service._new_count == 1 and published == [1, 1]
    task.cancel()
    await task


async def case_periodic_and_dropped_queue():
    state, service, published = build(periodic=0.1)
    task = asyncio.create_task(service._run())
    await asyncio.sleep(0.35)
    assert len(published) >= 2, "the periodic round publishes with no event: %s" % published
    first = state.queues[0]
    state.alive.discard(first)                              # the state dropped the slow queue
    await asyncio.sleep(0.25)
    assert len(state.queues) >= 2 and state.queues[1] in state.alive, "a fresh queue replaces the dropped one"
    task.cancel()
    await task
    assert state.released[-1] is state.queues[-1], "the last queue is the one released"


async def main():
    await case_watched_and_unwatched()
    await case_burst_keeps_last_count()
    await case_periodic_and_dropped_queue()


asyncio.run(main())
print("TUTTO OK")
