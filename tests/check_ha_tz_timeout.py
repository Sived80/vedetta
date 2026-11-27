# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The WebSocket handshake that reads Home Assistant's time zone does not wait forever: a server that accepts the connection and then says
nothing (or keeps sending other messages) ends the reading with a timeout, as the registry does, instead of hanging the task. No socket:
the WebSocket is a fake."""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import ha_registry, ha_tz  # noqa: E402

ha_registry.TIMEOUT_S = 0.05


class Silent:
    """Answers the messages in `script`, then never again."""
    def __init__(self, script):
        self.script = list(script)

    async def recv(self):
        if self.script:
            return json.dumps(self.script.pop(0))
        await asyncio.sleep(3600)

    async def send(self, _):
        pass


class Chatty(Silent):
    """After the login, only events that are not the answer to the request."""
    async def recv(self):
        if self.script:
            return json.dumps(self.script.pop(0))
        await asyncio.sleep(0.01)
        return json.dumps({"id": 99, "type": "event"})


async def ends(coro) -> str:
    try:
        await asyncio.wait_for(coro, 2)
    except asyncio.TimeoutError:
        return "timeout"
    except Exception as exc:          # noqa: BLE001
        return type(exc).__name__
    return "returned"


async def main():
    t0 = asyncio.get_running_loop().time()
    assert await ends(ha_tz._authenticate(Silent([]), "tok")) == "timeout"
    assert await ends(ha_tz._authenticate(Silent([{"type": "auth_required"}]), "tok")) == "timeout"
    assert await ends(ha_tz._get_config(Silent([]))) == "timeout"
    assert await ends(ha_tz._get_config(Chatty([]))) == "timeout"
    elapsed = asyncio.get_running_loop().time() - t0
    assert elapsed < 1.5, f"the handshake waited {elapsed:.1f} s: no timeout of its own"
    # a normal answer is still read
    ok = Silent([{"type": "auth_required"}, {"type": "auth_ok"}, {"id": 1, "success": True, "result": {"time_zone": "Europe/Rome"}}])
    await ha_tz._authenticate(ok, "tok")
    assert (await ha_tz._get_config(ok)) == {"time_zone": "Europe/Rome"}


asyncio.run(main())
print("ALL OK")
