"""Delivery of events to the open browsers (and the MQTT bridge): who is listening, and a bounded queue for each.

It knows nothing about devices or revisions: DeviceState stamps the revision and keeps the history needed to catch up."""
import asyncio

QUEUE_SIZE = 200


class EventBus:
    def __init__(self) -> None:
        self.subscribers: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_SIZE)
        self.subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.subscribers.discard(q)

    def is_subscribed(self, q: asyncio.Queue) -> bool:
        return q in self.subscribers

    def publish(self, event: dict) -> None:
        for q in list(self.subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Client too slow: it is disconnected, it will reconnect by itself and receive the missing differences through catch_up.
                self.subscribers.discard(q)
