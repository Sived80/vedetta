"""Memoria dei nomi Bonjour: un nome visto una volta resta, per MAC, anche quando il telefono torna a dormire."""
import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import i18n, mdns_listener, probe, roles  # noqa: E402

i18n.use("it")
mdns_listener.STORE_PATH = Path(tempfile.mkdtemp()) / "mdns_seen.json"
ARP = {"10.0.0.112": "42:4b:cd:00:00:a3"}
mdns_listener._mac_for_ip = lambda ip: ARP.get(ip)

# annuncio con nome scelto dall'utente (AirPlay) e modello nel TXT
mdns_listener.record("10.0.0.112", "_companion-link._tcp", "iPhone-di-Caio", '"model=iPhone15,2"')
card = mdns_listener.lookup("42:4B:CD:00:00:A3")
assert card and card["name"] == "iPhone-di-Caio" and card["model"] == "iPhone15,2" and "_companion-link._tcp" in card["services"], card
assert "10.0.0.112" not in mdns_listener.by_ip          # il MAC era noto: si tiene per MAC
assert mdns_listener.as_scan_info(card)["mdns_name"] == "iPhone-di-Caio"

# un nome migliore sostituisce quello vecchio; uno peggiore no
mdns_listener.record("10.0.0.112", "_http._tcp", "altro", "")
assert mdns_listener.lookup("42:4b:cd:00:00:a3")["name"] == "iPhone-di-Caio"

# MAC ancora ignoto: si tiene per IP e si lega al MAC appena l'ARP lo conosce
mdns_listener.record("10.0.0.50", "_airplay._tcp", "Tablet di Mevio", "")
assert mdns_listener.lookup(None, "10.0.0.50")["name"] == "Tablet di Mevio"
ARP["10.0.0.50"] = "aa:bb:cc:00:00:50"
mdns_listener._housekeeping()
assert "10.0.0.50" not in mdns_listener.by_ip and mdns_listener.lookup("AA:BB:CC:00:00:50")["name"] == "Tablet di Mevio"
# per IP vecchio di piu' di 14 giorni non vale
mdns_listener.by_ip["10.0.0.99"] = {"name": "Vecchio", "seen": time.time() - 15 * 86400}
assert mdns_listener.lookup(None, "10.0.0.99") is None

# salvataggio e ricarica
mdns_listener._save()
mdns_listener.by_mac.clear(); mdns_listener.by_ip.clear()
mdns_listener._load()
assert mdns_listener.lookup("42:4b:cd:00:00:a3")["name"] == "iPhone-di-Caio"

# nel probe: iPhone con MAC privato, scansione senza nome -> il nome ricordato diventa il nome del dispositivo
probe.ADAPTERS = {}
roles.roles_for = lambda ip: []
roles.upnp_types = lambda ip: []
phone = {"id": "ph", "name": "10.0.0.112", "ip": "10.0.0.112", "port": 80, "adapter": "generic", "scan_info": {}, "last_mac": "42:4B:CD:00:00:A3"}
res = asyncio.run(probe.probe_device(phone))
assert res["name"] == "iPhone-di-Caio" and res["auto_name"][:2] == ("iPhone-di-Caio", "mdns"), (res["name"], res["auto_name"])
# la scansione, se ha un nome, vince su quello ricordato
res = asyncio.run(probe.probe_device({**phone, "scan_info": {"mdns_name": "Nome nuovo"}}))
assert res["name"] == "Nome nuovo"
print("TUTTO OK")
