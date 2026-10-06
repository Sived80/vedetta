"""The user's time zone comes from Home Assistant: the nightly maintenance runs at 03:00 there, the log writes that time."""
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import applog, ha_registry, ha_tz, maintenance  # noqa: E402

# the configuration of Home Assistant
assert str(ha_tz.zone_from_config({"time_zone": "Europe/Rome", "latitude": 1})) == "Europe/Rome"
assert ha_tz.zone_from_config({"time_zone": "Nowhere/Atlantis"}) is None and ha_tz.zone_from_config({}) is None and ha_tz.zone_from_config(None) is None

# without Home Assistant the container's own time is used
ha_tz._state["zone"] = None
assert ha_tz.zone() is not None and abs(ha_tz.now().timestamp() - time.time()) < 5

# the night is 03:00 of THAT zone, not of Rome and not of UTC
ha_tz._state["zone"] = ZoneInfo("Pacific/Auckland")            # UTC+13 in October
moment = datetime(2026, 10, 6, 14, 0, tzinfo=timezone.utc)      # 03:00 there
assert maintenance.is_night(moment.astimezone(ha_tz.zone())) and not maintenance.is_night(moment)
assert not maintenance.is_night(datetime(2026, 10, 6, 3, 0, tzinfo=timezone.utc).astimezone(ha_tz.zone()))
# the log shows the same zone
assert applog._display_time(moment.timestamp()).endswith("03:00:00"), applog._display_time(moment.timestamp())
ha_tz._state["zone"] = ZoneInfo("Europe/Rome")
assert applog._display_time(moment.timestamp()).endswith("16:00:00")


# reading it from Home Assistant, with a fake WebSocket
class FakeWS:
    def __init__(self, replies):
        self.replies, self.sent = list(replies), []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def recv(self):
        return json.dumps(self.replies.pop(0))

    async def send(self, data):
        self.sent.append(json.loads(data))


def fake_module(ws):
    import types
    mod = types.ModuleType("websockets")
    mod.connect = lambda *a, **k: ws
    return mod


os.environ["SUPERVISOR_TOKEN"] = "test-token"
ws = FakeWS([{"type": "auth_required"}, {"type": "auth_ok"}, {"id": 1, "type": "result", "success": True, "result": {"time_zone": "America/Chicago"}}])
sys.modules["websockets"] = fake_module(ws)
ha_tz._state.update(zone=None, at=0.0)
assert asyncio.run(ha_tz.refresh()) is True and str(ha_tz.zone()) == "America/Chicago"
assert ws.sent[0] == {"type": "auth", "access_token": "test-token"} and ws.sent[1] == {"id": 1, "type": "get_config"}
# at most once an hour, unless forced
assert asyncio.run(ha_tz.refresh()) is False
# a refused or broken answer keeps the zone known and tries again in five minutes, not every minute
bad = FakeWS([{"type": "auth_required"}, {"type": "auth_invalid"}])
sys.modules["websockets"] = fake_module(bad)
assert asyncio.run(ha_tz.refresh(force=True)) is False and str(ha_tz.zone()) == "America/Chicago"
assert 200 < (ha_tz.REFRESH_S - (time.time() - ha_tz._state["at"])) <= 300
# no token (outside Home Assistant): nothing is asked
del os.environ["SUPERVISOR_TOKEN"]
assert asyncio.run(ha_tz.refresh(force=True)) is False
ha_tz._state["zone"] = ZoneInfo("Europe/Rome")
print("TUTTO OK")
