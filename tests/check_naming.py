"""Check of name choice and cleanup (runnable locally)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vedetta"))
from app import naming  # noqa: E402

# cleanup: DNS-SD escapes, domains, useless names
assert naming.clean_name(r"SONY\032XR-55X92K") == "SONY XR-55X92K"
assert naming.clean_name("mac-mini.local") == "mac-mini"
assert naming.clean_name("nas.fritz.box") == "nas"
assert naming.clean_name("iPhone-di-Tizio") == "iPhone-di-Tizio"
assert naming.clean_name("Xiaomi-14") == "Xiaomi-14"
assert naming.clean_name("Soggiorno TV") == "Soggiorno TV"
for junk in ["", None, "localhost", "unknown", "(unknown)", "192.168.50.50", "ip-192-168-50-50", "192-168-50-50",
             "AA:BB:CC:DD:EE:FF", "android-1a2b3c4d5e6f7a8b", "5c53de3b-esphome", "Chromecast-0a1b2c3d4e5f",
             r"amzn\.dmgr\05837F86A463D38E919EF206906B", "_airplay._tcp", "x._tcp.local", "-"]:
    assert naming.clean_name(junk) is None, junk

# choice by priority
assert naming.pick([("nmap", "pc-sala"), ("mdns", "Salotto")]) == ("Salotto", "mdns")
assert naming.pick([("dhcp", "android-1a2b3c4d5e6f7a8b"), ("nmap", None)]) == (None, None)  # everything discarded: the IP stays
assert naming.pick([("adapter", "shelly1-AB12"), ("mdns", "shelly1-AB12")])[1] == "adapter"
assert naming.pick([("dhcp", "Xiaomi-14"), ("netbios", "DESKTOP")]) == ("Xiaomi-14", "dhcp")

# when a scan can replace the name
ip = "10.0.0.5"
assert naming.is_better({"ip": ip, "name": ip}, "nmap")                                # still the IP
assert naming.is_better({"ip": ip}, "nmap")                                            # no name
assert not naming.is_better({"ip": ip, "name": "Cucina"}, "adapter")                   # name with no source: chosen by hand
assert not naming.is_better({"ip": ip, "name": "Cucina", "name_source": "user"}, "adapter")
assert naming.is_better({"ip": ip, "name": "pc", "name_source": "nmap"}, "mdns")       # better source
assert not naming.is_better({"ip": ip, "name": "Salotto", "name_source": "mdns"}, "dhcp")
assert not naming.is_better({"ip": ip, "name": "Salotto", "name_source": "mdns"}, "mdns")
print("OK")

# a name that says what the device is (known brand + model number) overtakes an opaque label of a more reliable source:
# an Android phone announced "expiscor" through the Alexa app service and "Xiaomi-14" through DHCP
assert naming.model_like("Xiaomi-14") and naming.model_like("Galaxy S23") and not naming.model_like("expiscor") and not naming.model_like("Samsung TV") and not naming.model_like(None)
assert naming.pick([("mdns", "expiscor"), ("dhcp", "Xiaomi-14")]) == ("Xiaomi-14", "dhcp")
assert naming.pick([("mdns", "Cucina"), ("dhcp", "Samsung-TV")]) == ("Cucina", "mdns")                # no model number: the chosen label stays
assert naming.pick([("mdns", "Galaxy-S23"), ("dhcp", "Xiaomi-14")]) == ("Galaxy-S23", "mdns")        # both say what they are: the usual order
assert naming.pick([("adapter", "shelly1-AB12"), ("dhcp", "Xiaomi-14")])[1] == "adapter"              # the device's own API still wins by far
phone = {"name": "expiscor", "name_source": "mdns", "ip": "10.0.0.9"}
assert naming.is_better(phone, "dhcp", "Xiaomi-14") and not naming.is_better(phone, "dhcp", "Samsung-TV") and not naming.is_better(phone, "dhcp")
assert not naming.is_better({**phone, "name_source": "user"}, "dhcp", "Xiaomi-14")                     # never over a name chosen by hand
assert not naming.is_better({"name": "Galaxy-S23", "name_source": "mdns", "ip": "10.0.0.9"}, "dhcp", "Xiaomi-14")
# devices already named: the same rule corrects the saved automatic name at the next check
cands = [("mdns", "expiscor"), ("dhcp", "Xiaomi-14")]
assert naming.upgrade(phone, cands) == ("Xiaomi-14", "dhcp")
assert naming.upgrade({**phone, "name": "Xiaomi-14", "name_source": "dhcp"}, cands) is None             # already the best
assert naming.upgrade({**phone, "name_source": "user"}, cands) is None
assert naming.upgrade({**phone, "name_source": "ha_user"}, cands) is None
assert naming.upgrade({**phone, "name_source": None}, cands) is None
print("TUTTO OK")
