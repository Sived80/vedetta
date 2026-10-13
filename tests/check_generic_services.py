"""A declared mDNS service that any general responder publishes is a weak clue, not a declaration of what the device is. "_workstation._tcp" is published by avahi-daemon when its option publish-workstation is on
(default "no" in some versions of avahi-daemon.conf, "yes" in others) and by recent macOS: an embedded Linux box (a video door entry unit) has it as a PC has. Alone it is below the minimum of points for
a type (the card stays "generic" and is looked at again by the state of analysis); with another clue of a computer it still counts. A service that does say it (Remote Desktop) keeps its weight."""
import os
import sys
import tempfile

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import ha_data  # noqa: E402


def card(services, ports=(), name="Bticino-1", confirmed=False):
    return {"id": "x", "ip": "10.0.0.50", "name": name, "name_generated": False, "brand": None, "vendor": None, "vendor_role": None,
            "extra": ({"mdns_services": services} if services else {}), "scanned_ports": [{"label": p, "confirmed": confirmed} for p in ports], "ha_registry": None, "is_mobile": False}


def group(device):
    return ha_data.infer_type(device, None)


assert group(card("_workstation._tcp")) == "generic", group(card("_workstation._tcp"))
assert group(card(None, ports=("3389/tcp",))) == "generic", "an unconfirmed port alone is below the minimum"
assert group(card("_workstation._tcp", ports=("3389/tcp",))) == "pc", "a weak clue still adds to another weak clue of a computer"
assert group(card("_rdp._tcp")) == "pc", "Remote Desktop says what the device is"
assert group(card("_workstation._tcp, _rdp._tcp")) == "pc"
print("TUTTO OK")
