"""Cases reported on GitHub: a Chromebook is not an iPhone, and a Fairphone is a phone."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.recognition import brands, identity
from app.scan import dhcp, probe
from app.ha import ha_data  # noqa: E402

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
assert brands.is_phone_only("Fairphone") and brands.is_phone_only("Murena") and not brands.is_phone_only("Xiaomi") and not brands.is_phone_only(None)    # the list is data (brands.json)
assert probe._is_mobile("Fairphone 3") and not probe._is_mobile("FP3")
factory = "d4:f5:47:00:00:02"
dhcp.seen[factory] = {"prl": "1,3,6,15,26,28,51,58,59,43", "vendor_class": "android-dhcp-15", "hostname": "FP3"}
assert not identity.mobile_assess(mac=factory, name_is_mobile=False, has_ports=None)["mobile"]                        # the Android class alone is not enough
assert identity.mobile_assess(mac=factory, name_is_mobile=brands.is_phone_only("Fairphone"), has_ports=None)["mobile"]  # with the brand it is
# a TV box that is also Android is not turned into a phone by this
assert not identity.mobile_assess(mac=factory, name_is_mobile=brands.is_phone_only("Sony"), has_ports=None, media_receiver=True)["mobile"]

# --- Sky boxes and Amazon Echo, read from a real export (their evidence.json): Sky Q was a tie audio/media, Echo devices with only
# the Matter service were "Network equipment" because "matter" was a word of the hub kind
def box(name, brand, extra, ports):
    return {"id": "x", "ip": "10.0.0.7", "name": name, "brand": brand, "vendor": brand, "extra": extra,
            "scanned_ports": [{"label": f"{n} · {s}", "confirmed": True} for n, s in ports], "is_mobile": False}


sky_ports = [(5000, "Apple AirTunes rtspd"), (8008, "tcpwrapped"), (8080, "http-proxy")]
sky_extra = {"mdns_services": "_airplay._tcp, _http._tcp, _raop._tcp", "http_server": "Sky"}
assert ha_data.infer_type(box("Sky Q", "Sky", {**sky_extra, "mdns_model": "ESi240"}, sky_ports)) == "media"
assert ha_data.infer_type(box("Sky Q Mini", "Sky", {**sky_extra, "mdns_model": "EM150EU", "http_server": "vws/1.0"}, sky_ports)) == "media"
assert ha_data.infer_type(box("Sky", "Sky", sky_extra, sky_ports)) == "media"           # even without the model: AirPlay words do not say "audio"
# a real soundbar with AirPlay is still audio
assert ha_data.infer_type(box("Soundbar", "Yamaha", {"mdns_services": "_airplay._tcp, _raop._tcp"}, [])) == "audio"
matter = {"mdns_services": "_I163C04EE3B7C500E._sub._matter._tcp, _matter._tcp"}
assert ha_data.infer_type(box("Amazon", "Amazon", matter, [(4070, "Nagios NSCA"), (55443, "unknown")])) != "router"
assert ha_data.infer_type(box("Alexa", "Amazon", {"mdns_services": "_spotify-connect._tcp, _matter._tcp"}, [])) == "audio"
assert ha_data.infer_type(box("Zigbee bridge", "Tasmota", {}, [])) == "router"        # the hub kind keeps its real words
# --- a Xiaomi announced as "expiscor" by mDNS and "Xiaomi-14" by DHCP: the hostname says phone even if it is not the displayed name
assert probe._is_mobile("Xiaomi-14") and not probe._is_mobile("expiscor")
print("TUTTO OK")
