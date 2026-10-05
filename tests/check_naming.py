"""Verifica scelta e pulizia dei nomi (eseguibile in locale)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vedetta"))
from app import naming  # noqa: E402

# pulizia: escape DNS-SD, domini, nomi inutili
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

# scelta per priorita'
assert naming.pick([("nmap", "pc-sala"), ("mdns", "Salotto")]) == ("Salotto", "mdns")
assert naming.pick([("dhcp", "android-1a2b3c4d5e6f7a8b"), ("nmap", None)]) == (None, None)  # tutto scartato: resta l'IP
assert naming.pick([("adapter", "shelly1-AB12"), ("mdns", "shelly1-AB12")])[1] == "adapter"
assert naming.pick([("dhcp", "Xiaomi-14"), ("netbios", "DESKTOP")]) == ("Xiaomi-14", "dhcp")

# quando una scansione puo' sostituire il nome
ip = "10.0.0.5"
assert naming.is_better({"ip": ip, "name": ip}, "nmap")                                # ancora l'IP
assert naming.is_better({"ip": ip}, "nmap")                                            # senza nome
assert not naming.is_better({"ip": ip, "name": "Cucina"}, "adapter")                   # nome senza origine: scelto a mano
assert not naming.is_better({"ip": ip, "name": "Cucina", "name_source": "user"}, "adapter")
assert naming.is_better({"ip": ip, "name": "pc", "name_source": "nmap"}, "mdns")       # fonte migliore
assert not naming.is_better({"ip": ip, "name": "Salotto", "name_source": "mdns"}, "dhcp")
assert not naming.is_better({"ip": ip, "name": "Salotto", "name_source": "mdns"}, "mdns")
print("OK")
