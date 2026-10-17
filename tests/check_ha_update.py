"""The update state of this add-on (ha_update): the card that the Supervisor gives for the add-on itself is read as {available, installed, latest}; a card without a
version says nothing; no token (outside Home Assistant), a Supervisor that is down or too slow keep the last answer and ask again soon; a good answer waits ten minutes;
the one thing asked is the add-on's own card, with the token as a bearer (read-only, no other address)."""
import asyncio
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import ha_registry, ha_update  # noqa: E402

assert ha_update.parse({"version": "0.7.1", "version_latest": "0.7.2", "update_available": True}) == {"available": True, "installed": "0.7.1", "latest": "0.7.2"}
assert ha_update.parse({"version": "0.7.1-debug", "version_latest": "0.7.1-debug", "update_available": False}) == {"available": False, "installed": "0.7.1-debug", "latest": "0.7.1-debug"}
assert ha_update.parse({"version": "0.7.1"}) == {"available": False, "installed": "0.7.1", "latest": ""}       # a field missing is "no update", not an error
for bad in (None, {}, [], "x", {"version": ""}, {"update_available": True}):
    assert ha_update.parse(bad) is None, bad

CALLS: list = []


async def go():
    assert ha_update.snapshot() is None
    ha_registry.token = lambda: None
    assert await ha_update.refresh() == ha_update.RETRY_S and ha_update.snapshot() is None      # outside Home Assistant: nothing, and asks again later

    ha_registry.token = lambda: "tok"

    async def ok(tok):
        CALLS.append(tok)
        return {"version": "0.7.1", "version_latest": "0.7.2", "update_available": True}
    ha_update._fetch = ok
    assert await ha_update.refresh() == ha_update.REFRESH_S
    assert CALLS == ["tok"], CALLS
    assert ha_update.snapshot() == {"available": True, "installed": "0.7.1", "latest": "0.7.2"}

    async def down(tok):
        raise RuntimeError("down")
    ha_update._fetch = down
    assert await ha_update.refresh() == ha_update.RETRY_S
    assert ha_update.snapshot()["latest"] == "0.7.2"                                              # the last answer stays

    async def slow(tok):
        await asyncio.sleep(5)
    ha_update._fetch = slow
    ha_update.TIMEOUT_S = 0.05
    assert await ha_update.refresh() == ha_update.RETRY_S
    assert ha_update.snapshot()["latest"] == "0.7.2"

    async def done(tok):
        return {"version": "0.7.2", "version_latest": "0.7.2", "update_available": False}
    ha_update._fetch = done
    ha_update.TIMEOUT_S = 8
    assert await ha_update.refresh() == ha_update.REFRESH_S
    assert ha_update.snapshot() == {"available": False, "installed": "0.7.2", "latest": "0.7.2"}  # updated: the dot goes away


asyncio.run(go())

# the address and the header of the real call (a fake client in place of httpx)
sys.modules.pop("httpx", None)
import types  # noqa: E402

SEEN: dict = {}


class FakeReply:
    def raise_for_status(self):
        pass

    def json(self):
        return {"result": "ok", "data": {"version": "1", "version_latest": "2", "update_available": True}}


class FakeClient:
    def __init__(self, timeout=None):
        SEEN["timeout"] = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None):
        SEEN["url"], SEEN["headers"] = url, headers
        return FakeReply()


sys.modules["httpx"] = types.SimpleNamespace(AsyncClient=FakeClient)
del ha_update._fetch                                                                              # back to the module's own function
import importlib  # noqa: E402
importlib.reload(ha_update)
assert asyncio.run(ha_update._fetch("abc")) == {"version": "1", "version_latest": "2", "update_available": True}
assert SEEN["url"] == "http://supervisor/addons/self/info" and SEEN["headers"] == {"Authorization": "Bearer abc"}, SEEN
print("TUTTO OK")
