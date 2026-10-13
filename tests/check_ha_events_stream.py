"""The event stream of the page (routes/ha.api_ha_events, server-sent events), with a fake state and a fake request: it opens with the retry hint, then the events the client missed, then the picture of the
moment (poll, activity, new devices, roles), then every event of the bus as a frame; when nothing comes for a while it sends a ping comment, and it ends (releasing its queue) when the state dropped the queue or
the client went away. Written on the code before it was flattened and kept passing after it (differential proof). The wait of 15 seconds is cut to a few hundredths of a second for the test."""
import asyncio
import json
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.routes import ha as routes_ha  # noqa: E402

real_wait_for = asyncio.wait_for
asyncio.wait_for = lambda awaitable, timeout=None: real_wait_for(awaitable, 0.05)      # the quiet period of the stream, short


class FakeState:
    def __init__(self, missed=()):
        self.queue, self.alive, self.released, self.missed = None, True, [], list(missed)

    def subscribe(self):
        self.queue = asyncio.Queue()
        return self.queue

    def unsubscribe(self, q):
        self.released.append(q)

    def is_subscribed(self, q):
        return self.alive

    def catch_up(self, rev):
        self.asked_rev = rev
        return self.missed

    def poll_info(self):
        return {"type": "poll", "n": 1}

    def activity_info(self):
        return {"type": "activity", "n": 2}

    async def new_devices_event(self):
        return {"type": "new_devices", "count": 3}


class FakeRequest:
    def __init__(self, disconnect_after=None):
        self.calls, self.disconnect_after = 0, disconnect_after

    async def is_disconnected(self):
        self.calls += 1
        return self.disconnect_after is not None and self.calls >= self.disconnect_after

    class headers:
        @staticmethod
        def get(*a, **k):
            return None

    query_params = {}
    cookies = {}


routes_ha.roles.event = lambda: {"type": "roles", "n": 4}
routes_ha.analysis_view.event = lambda: {"type": "analysis", "n": 5}
routes_ha.ha_data.config_map = lambda: {}


def frame(event):
    return "event: " + event["type"] + "\ndata: " + json.dumps(event) + "\n\n"


async def collect(state, request, put=(), limit=40, rev=7):
    routes_ha.state = state
    response = await routes_ha.api_ha_events(request, rev=rev)
    for event in put:
        state.queue.put_nowait(event)
    out = []
    async for chunk in response.body_iterator:
        out.append(chunk)
        if len(out) >= limit:
            break
    await response.body_iterator.aclose()
    return out


async def main():
    # 1) the opening: retry, missed events, poll, activity, new devices, roles, the states of analysis; then the events of the bus; the client goes away at the second quiet period
    state = FakeState(missed=[{"type": "removed", "id": "x"}, {"type": "poll", "n": 0}])
    out = await collect(state, FakeRequest(disconnect_after=2), put=[{"type": "poll", "n": 9}, {"type": "removed", "id": "y"}])
    assert state.asked_rev == 7
    expected = ["retry: 3000\n\n", frame({"type": "removed", "id": "x"}), frame({"type": "poll", "n": 0}), frame({"type": "poll", "n": 1}), frame({"type": "activity", "n": 2}),
                frame({"type": "new_devices", "count": 3}), frame({"type": "roles", "n": 4}), frame({"type": "analysis", "n": 5}), frame({"type": "poll", "n": 9}), frame({"type": "removed", "id": "y"}), ": ping\n\n"]
    assert out == expected, out
    assert state.released == [state.queue], "the queue is released when the stream ends"

    # 2) the state dropped the queue (too slow): the stream ends at the first quiet period, with no ping
    state = FakeState()
    state.alive = False
    out = await collect(state, FakeRequest())
    assert out[-1] == frame({"type": "analysis", "n": 5}) and ": ping\n\n" not in out and state.released == [state.queue], out

    # 3) quiet and nobody leaves: a ping every quiet period
    state = FakeState()
    out = await collect(state, FakeRequest(), limit=9)
    assert out.count(": ping\n\n") >= 2 and out[0] == "retry: 3000\n\n", out
    assert state.released == [state.queue]


asyncio.run(main())
asyncio.wait_for = real_wait_for
print("TUTTO OK")
