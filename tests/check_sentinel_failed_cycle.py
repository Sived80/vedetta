"""A cycle that fails never makes the Sentinel forget a "down" already sent: after a restart the cards are still empty until the first
cycle that succeeds, and an end of cycle run with them would close every open "down" (forget_gone), so its "back" would never go out.
After a cycle that succeeds, a card really gone still closes its "down". Found by the review of 1.0.1.
Fake state, temporary data folder, invented cards.
    python tests/check_sentinel_failed_cycle.py"""
import asyncio
import os
import sys
import tempfile
import time
from types import SimpleNamespace

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import sentinel_view, state_cycle  # noqa: E402
from app.ha import ha_data  # noqa: E402
from app.sentinel import DOWN, SENT  # noqa: E402

ha_data.config_map = lambda: {"a": {"id": "a", "watch": "1"}}
alerts = []
emit = lambda message, key, **params: alerts.append(key)    # noqa: E731

# a "down" sent for card "a" ten minutes before the restart (recent: a closed event older than a week would be pruned anyway)
T0 = time.time() - 600
sentinel_view.on_presence({"id": "a", "name": "Lamp", "ip": "192.0.2.10"}, True, T0)
sentinel_view.on_presence({"id": "a", "name": "Lamp", "ip": "192.0.2.10"}, False, T0 + 100)
sent = sentinel_view.after_cycle({"a": {"id": "a", "online": False}}, emit, now=T0 + 500)
assert [(e["kind"], e["card"]) for e in sent] == [(DOWN, "a")], sent


def down_event():
    return next(e for e in sentinel_view.sentinel().events if e["kind"] == DOWN and e["card"] == "a")


async def failing_poll():
    raise RuntimeError("the router did not answer")


async def run(poll):
    fake = SimpleNamespace(_force=False, _cause="", _last_start=0.0, _polled_ok=False, devices={}, emit_alert=emit, ready=asyncio.Event(),
                           poll_once=poll, _note_start=lambda cause: None, _note_end=lambda start: None)
    await state_cycle._run_cycle(fake, 0)
    return fake


# after the restart: no card yet, and the first cycle fails
fake = asyncio.run(run(failing_poll))
assert fake.ready.is_set()
ev = down_event()
assert ev["state"] == SENT and not ev.get("closed"), ev


# a cycle that succeeds without card "a" (deleted while away): its "down" is closed, as before
async def good_poll():
    return None

asyncio.run(run(good_poll))
assert down_event().get("closed") is True, down_event()
print("check_sentinel_failed_cycle: ok")
