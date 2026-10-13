"""The event bus (app/eventbus.py): delivery to every listener, a slow listener is dropped (not blocked), unsubscribe is idempotent."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import eventbus  # noqa: E402


async def main():
    bus = eventbus.EventBus()
    a, b = bus.subscribe(), bus.subscribe()
    assert bus.is_subscribed(a) and bus.is_subscribed(b) and a.maxsize == eventbus.QUEUE_SIZE
    bus.publish({"n": 1})
    assert a.get_nowait() == {"n": 1} and b.get_nowait() == {"n": 1}
    for i in range(eventbus.QUEUE_SIZE):                # b never reads: it fills up and is disconnected, a keeps working
        bus.publish({"n": i})
        a.get_nowait()
    bus.publish({"n": "overflow"})
    assert not bus.is_subscribed(b) and bus.is_subscribed(a) and a.get_nowait() == {"n": "overflow"}
    bus.unsubscribe(b)                                  # already gone: no error
    bus.unsubscribe(a)
    bus.publish({"n": 2})                               # nobody listening: no error
    assert not bus.subscribers


asyncio.new_event_loop().run_until_complete(main())
print("TUTTO OK")
