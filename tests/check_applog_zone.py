"""The log writes its times in the zone that ha_tz registers (applog does not import ha_tz): no provider -> Europe/Rome; ha_tz imported -> its zone;
a provider that fails -> Europe/Rome again."""
import os
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import applog  # noqa: E402

assert applog._zone_provider["fn"] is None
assert applog._display_time(0) == "1970-01-01 01:00:00", applog._display_time(0)     # Europe/Rome in January 1970 is UTC+1

from app.ha import ha_tz  # noqa: E402  (importing it registers the zone)

assert applog._zone_provider["fn"] is ha_tz.zone
ha_tz._state["zone"] = ZoneInfo("UTC")
assert applog._display_time(0) == "1970-01-01 00:00:00"
ha_tz._state["zone"] = ZoneInfo("Asia/Tokyo")
assert applog._display_time(0) == "1970-01-01 09:00:00"

applog.set_zone_provider(lambda: 1 / 0)
assert applog._display_time(0) == "1970-01-01 01:00:00"                               # a failing provider falls back to Europe/Rome
applog.set_zone_provider(None)
assert applog._display_time(0) == "1970-01-01 01:00:00"
print("TUTTO OK")
