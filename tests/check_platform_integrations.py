"""A Home Assistant integration that covers a whole PLATFORM (several brands on the same chip and protocol) says what the device does, as the Sonos or HEOS ones do. LinkPlay (WiiM, Arylic, Audio Pro and
other makers of streamers and amplifiers on the LinkPlay platform) is an audio platform: a device that Home Assistant drives with it is audio, even if it also speaks Cast, which televisions speak too.
Seen in an export: a WiiM amplifier declared Cast + AirPlay + RAOP + LinkPlay and was read as media."""
import os
import sys
import tempfile

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import ha_data  # noqa: E402


def streamer(domains, services="_airplay._tcp, _googlecast._tcp, _googlezone._tcp, _linkplay._tcp, _raop._tcp"):
    return {"id": "x", "ip": "10.0.0.231", "name": "WiiM Amp", "name_generated": False, "brand": "WiiM", "vendor": "AMPAK", "vendor_role": "component",
            "extra": {"mdns_services": services, "mdns_model": "WiiM Amp", "ha_model": "WiiM Amp"},
            "scanned_ports": [{"label": "8008 http", "confirmed": False}, {"label": "8009 ajp13", "confirmed": False}, {"label": "7000 rtspd", "confirmed": False}],
            "ha_registry": {"domains": domains, "entity_domains": ["media_player"]}, "is_mobile": False}


assert ha_data.infer_type(streamer(["linkplay"]), None) == "audio", ha_data.infer_type(streamer(["linkplay"]), None)
assert ha_data.infer_type(streamer(["sonos"]), None) == "audio", "the control: a known audio platform"
assert ha_data.infer_type(streamer(["cast"], "_googlecast._tcp"), None) == "media", "Cast alone is still a media device"
print("TUTTO OK")
