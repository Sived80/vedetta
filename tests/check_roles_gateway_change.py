"""After a change of network the gateway tile follows within a minute or so, not after the next roles refresh (every REFRESH_S = 10 min):
the wait between two refreshes looks every GATEWAY_CHECK_S whether the gateway the host routes through is not the one the roles show, and
ends early when it changed (seen in the simulator, S29 run again on 08/11: the tile kept the old gateway for the whole 7 minutes).
    python tests/check_roles_gateway_change.py"""
import asyncio
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.recognition import roles  # noqa: E402

roles._rt.roles["by_ip"] = {"192.168.0.1": {"gateway": "route", "dns": "offer"}}
gw = {"now": "192.168.0.1"}
roles.default_gateway = lambda: gw["now"]
assert not roles._gateway_changed(), "same gateway"
gw["now"] = None
assert not roles._gateway_changed(), "no gateway read: nothing to compare"
gw["now"] = "192.168.50.1"
assert roles._gateway_changed(), "the host routes through another gateway"
roles._rt.roles["by_ip"] = {}
assert roles._gateway_changed(), "the roles show no gateway yet and one is there"

SLEPT: list = []


async def fake_sleep(s):
    SLEPT.append(s)


roles.asyncio.sleep = fake_sleep
gw["now"] = None
roles._rt.roles["by_ip"] = {"192.168.0.1": {"gateway": "route"}}
asyncio.run(roles._wait_next())
assert sum(SLEPT) >= roles.REFRESH_S and max(SLEPT) <= roles.GATEWAY_CHECK_S, "no change: the whole wait, in short steps"
SLEPT.clear()
calls = {"n": 0}


def changes_on_third():
    calls["n"] += 1
    return "192.168.50.1" if calls["n"] >= 3 else "192.168.0.1"


roles.default_gateway = changes_on_third
asyncio.run(roles._wait_next())
assert len(SLEPT) == 3, ("the wait ends at the first check that sees the change", SLEPT)
print("check_roles_gateway_change: ok")
