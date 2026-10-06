"""Cases reported on GitHub: a Chromebook is not an iPhone, and a Fairphone is a phone."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import brands, dhcp, ha_data, identity, probe  # noqa: E402

# --- #1: ChromeOS asks for the same DHCP options as iOS; its vendor class tells it apart
assert dhcp._os_family("1,121,3,6,15,119,252", "chromeOS") == "chromeos"
assert dhcp._os_family("1,121,3,6,15,119,252", "ChromeOS 15236") == "chromeos"
assert dhcp._os_family("1,121,3,6,15,119,252", None) == "ios"                       # an iPhone has no vendor class: unchanged
assert dhcp._os_family("1,121,3,6,15,119,252,95,44,46", "") == "macos" and dhcp._os_family(None, "android-dhcp-15") == "android"
mac = "9a:42:31:00:00:01"                                                           # a private address, as a Chromebook uses
dhcp.seen[mac] = {"prl": "1,121,3,6,15,119,252", "vendor_class": "chromeOS", "hostname": ""}
score, _ = dhcp.mobile_score(mac, False, None)
assert not identity.mobile_assess(mac=mac, name_is_mobile=False, has_ports=None)["mobile"] and score < 3, score
# no Apple: the brand never comes from a family that is not iOS or macOS
assert brands.resolve(None, names=[], upnp_manufacturer=None, declared=[], web_text=None, os_family="chromeos", is_gateway=False)["brand"] is None
assert brands.resolve(None, names=[], upnp_manufacturer=None, declared=[], web_text=None, os_family="ios", is_gateway=False)["brand"] == "Apple"
# and the group is Computers: "chromeos" in the DHCP class counts as a laptop word
device = {"id": "c1", "ip": "10.0.0.9", "name": "10.0.0.9", "extra": {"dhcp_class": "chromeOS"}, "scanned_ports": [], "is_mobile": False}
assert ha_data.infer_type(device) == "pc", ha_data.type_scores(device)

# --- #2: Fairphone (Android class, factory MAC, no phone word in the name FP3) is a phone through its brand
assert probe._phone_brand("Fairphone") and probe._phone_brand("Murena") and not probe._phone_brand("Xiaomi") and not probe._phone_brand(None)
assert probe._is_mobile("Fairphone 3") and not probe._is_mobile("FP3")
factory = "d4:f5:47:00:00:02"
dhcp.seen[factory] = {"prl": "1,3,6,15,26,28,51,58,59,43", "vendor_class": "android-dhcp-15", "hostname": "FP3"}
assert not identity.mobile_assess(mac=factory, name_is_mobile=False, has_ports=None)["mobile"]                        # the Android class alone is not enough
assert identity.mobile_assess(mac=factory, name_is_mobile=probe._phone_brand("Fairphone"), has_ports=None)["mobile"]  # with the brand it is
# a TV box that is also Android is not turned into a phone by this
assert not identity.mobile_assess(mac=factory, name_is_mobile=probe._phone_brand("Sony"), has_ports=None, media_receiver=True)["mobile"]
print("TUTTO OK")
