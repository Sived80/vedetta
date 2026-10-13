"""The reading of the Home Assistant registries over the websocket (ha_registry._fetch), with a fake websocket: the token is needed; the server must greet with auth_required and accept the token; the four
registries are asked one after the other with ids 1 to 4 and the answer with the same id is the one that counts (events with other ids that arrive in between are skipped); a refused command is an error
that names it; a result that is empty becomes an empty list. Written on the code before it was flattened and kept passing after it (differential proof). Nothing here talks to a real server."""
import asyncio
import json
import os
import sys
import tempfile
import types

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import ha_registry  # noqa: E402

SENT: list = []
CONNECT: list = []


class FakeWs:
    def __init__(self, script):
        self.script = list(script)

    async def recv(self):
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return json.dumps(item) if not isinstance(item, str) else item

    async def send(self, text):
        SENT.append(json.loads(text))


class Connection:
    def __init__(self, ws):
        self.ws = ws

    async def __aenter__(self):
        return self.ws

    async def __aexit__(self, *exc):
        return False


def install(script):
    fake = types.ModuleType("websockets")
    fake.connect = lambda url, **kw: (CONNECT.append((url, kw)), Connection(FakeWs(script)))[1]
    sys.modules["websockets"] = fake


def fetch(script, token="tok"):
    del SENT[:], CONNECT[:]
    install(script)
    if token is None:
        os.environ.pop("SUPERVISOR_TOKEN", None)
    else:
        os.environ["SUPERVISOR_TOKEN"] = token
    return asyncio.run(ha_registry._fetch())


def fails(script, text, token="tok"):
    try:
        fetch(script, token)
    except RuntimeError as exc:
        assert text in str(exc), (text, str(exc))
        return
    raise AssertionError("it must fail with: " + text)


HELLO = [{"type": "auth_required"}, {"type": "auth_ok"}]


def answers(*items):
    return [{"id": i, "type": "result", "success": True, "result": r} for i, r in enumerate(items, start=1)]


# 1) the good run: four registries, asked in order with ids 1-4, the token sent once
out = fetch(HELLO + answers([{"id": "d1"}], [{"entity_id": "light.a"}], [{"area_id": "kitchen"}], [{"entry_id": "e1"}]))
assert out == {"devices": [{"id": "d1"}], "entities": [{"entity_id": "light.a"}], "areas": [{"area_id": "kitchen"}], "entries": [{"entry_id": "e1"}]}, out
assert SENT == [{"type": "auth", "access_token": "tok"}, {"id": 1, "type": "config/device_registry/list"}, {"id": 2, "type": "config/entity_registry/list"},
                {"id": 3, "type": "config/area_registry/list"}, {"id": 4, "type": "config_entries/get"}], SENT
assert CONNECT[0][0] == ha_registry.WS_URL and CONNECT[0][1] == {"max_size": 64 * 1024 * 1024, "open_timeout": ha_registry.TIMEOUT_S}, CONNECT

# 2) events with another id in between are skipped; an empty or missing result is a list
mixed = HELLO + [{"type": "event", "id": 99}] + answers([1])[:1] + [{"id": 7, "type": "result", "success": True, "result": [9]}] + [
    {"id": 2, "type": "result", "success": True, "result": None}, {"id": 3, "type": "result", "success": True}, {"id": 4, "type": "result", "success": True, "result": []}]
out = fetch(mixed)
assert out == {"devices": [1], "entities": [], "areas": [], "entries": []}, out

# 3) the errors
fails([], "SUPERVISOR_TOKEN", token=None)
fails([{"type": "something"}], "risposta inattesa: something")
fails([{"type": "auth_required"}, {"type": "auth_invalid"}], "autenticazione rifiutata: auth_invalid")
fails(HELLO + [{"id": 1, "type": "result", "success": False, "error": {"code": "unauthorized"}}], "config/device_registry/list: {'code': 'unauthorized'}")
fails(HELLO + answers([1], [2]) + [{"id": 3, "type": "result", "success": False, "error": "no"}], "config/area_registry/list: no")
# a message that is not JSON, or a server that goes quiet, ends the reading with the error of the library
try:
    fetch(HELLO + ["not json"])
    raise AssertionError("must fail")
except ValueError:
    pass
print("TUTTO OK")
