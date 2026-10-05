"""A device that receives video is not a phone, even if it is called "Android"
(real data of the Fire TV Stick, 2026-10-04). Generic rule, no special case."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.identity import mobile_assess  # noqa: E402
from app.probe import _is_mobile, _media_receiver  # noqa: E402

fire = {"mdns_services": "_amzn-wplay._tcp"}
assert _media_receiver("10.0.0.3", fire, [{"label": "40027 · Amazon FireTV Stick", "confirmed": True}])
assert _media_receiver("10.0.0.4", {"mdns_services": "_googlecast._tcp"}, [])
assert not _media_receiver("10.0.0.5", {"mdns_services": "_airplay._tcp, _companion-link._tcp"}, [])  # Mac/iPhone
assert not _media_receiver("10.0.0.6", {}, [{"label": "8009 · tv-guess", "confirmed": False}])  # service not certain
assert not _is_mobile("Android") and _is_mobile("Galaxy-S23")
# Fire TV: "Android" in the name + receives video -> not mobile.
assert not mobile_assess(mac="F8:54:B8:00:00:AB", name_is_mobile=False, name_weak=True, has_ports=True, media_receiver=True)["mobile"]
# Android phone: "Android" + private MAC -> mobile.
assert mobile_assess(mac="3E:E3:41:00:00:AF", name_is_mobile=False, name_weak=True, has_ports=True)["mobile"]
# Phone name: mobile.
assert mobile_assess(mac="3E:E3:41:00:00:AF", name_is_mobile=True, has_ports=True)["mobile"]
print("TUTTO OK")
