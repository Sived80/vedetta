"""Verifica identita' (marca a due livelli, batteria, mobile) sui casi reali della LAN.
Eseguibile in locale; senza app.applog (zoneinfo) lo si simula."""
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vedetta"))
try:
    import app.applog  # noqa: F401
except Exception:
    import logging
    stub = types.ModuleType("app.applog")
    stub.logger = logging.getLogger("dashboard")
    sys.modules["app.applog"] = stub

from app import brands, dhcp, identity, scanner  # noqa: E402
from app.history import History  # noqa: E402

# nessuna regola dell'utente di mezzo
brands._USER_PATH = Path(tempfile.mkdtemp()) / "brands.json"
brands._cache["stamp"] = None

ROUTER = "B0:19:21:00:00:A9"      # router .1: TP-Link vero
PROXMOX_HOST = "E0:D3:62:00:00:AC"  # server .201: scheda di rete TP-Link
VM = "BC:24:11:00:00:A4"          # VM/LXC: MAC generato da Proxmox
BOUFFALO = "B4:E8:42:00:00:A1"    # IoT .102: chip Bouffalo Lab
ESP = "8C:AA:B5:00:00:A2"         # IoT con chip Espressif
PRIVATE = "4E:3A:FD:00:00:A5"     # MAC casuale di un telefono
SONY = "00:01:4A:11:22:33"       # prefisso Sony vero
SONY_TV = "38:B8:00:00:00:A8"    # TV Sony .113: il modulo Wi-Fi e' Wistron NeWeb


def ident(mac, **kw):
    return identity.identify_brand(mac, **kw)


# --- marca a due livelli ---
r = ident(ROUTER, is_gateway=True)
assert (r["brand"], r["brand_source"], r["vendor"], r["vendor_role"]) == ("TP-Link", "oui", "TP-Link", "dual"), r
r = ident(ROUTER)  # senza conferma un produttore "dual" non e' una marca
assert r["brand"] is None and r["vendor"] == "TP-Link" and r["vendor_role"] == "dual", r
r = ident(PROXMOX_HOST)  # scheda TP-Link in un server: NON e' un TP-Link
assert r["brand"] is None and r["vendor"] == "TP-Link", r
r = ident(PROXMOX_HOST, web_text="Proxmox Virtual Environment")  # il prodotto e' Proxmox
assert (r["brand"], r["brand_source"], r["brand_confidence"]) == ("Proxmox", "web", "high"), r
r = ident(VM)
assert r["brand"] is None and r["vendor"] == "Proxmox" and r["vendor_role"] == "virtual", r
r = ident(BOUFFALO)
assert r["brand"] is None and r["vendor"] == "Bouffalo Lab" and r["vendor_role"] == "component", r
r = ident(ESP)
assert r["brand"] is None and r["vendor_role"] == "component"
r = ident(ESP, names=["shelly1-8CAAB50000A2"])
assert (r["brand"], r["brand_source"], r["vendor"]) == ("Shelly", "name", "Espressif"), r
r = ident(PRIVATE)
assert r["vendor"] is None and r["vendor_role"] == "private" and r["brand"] is None, r
r = ident(SONY)
assert (r["brand"], r["brand_source"], r["brand_confidence"], r["vendor_role"]) == ("Sony", "oui", "medium", "brand"), r
r = ident(SONY_TV)  # il modulo non e' la marca...
assert r["brand"] is None and r["vendor_role"] == "component", r
assert ident(SONY_TV, names=["SONY XR-55X92K"])["brand"] == "Sony"  # ...il nome si'
# produttore dichiarato (UPnP/mDNS): solo se e' una marca della tabella
assert ident(BOUFFALO, upnp_manufacturer="Sonos, Inc.")["brand"] == "Sonos"
assert ident(BOUFFALO, upnp_manufacturer="Justin Maggard")["brand"] is None
assert ident(PRIVATE, declared=["Sony Corporation"])["brand_source"] == "declared"
assert ident(PRIVATE, names=["iPhone15,2"])["brand"] == "Apple"
assert ident(PRIVATE, os_family="ios")["brand_source"] == "dhcp"
# un utente puo' rinominare il produttore: cambia anche il ruolo (non e' piu' un chip)
brands.add_rule("vendor", "bouffalo", "Tuya")
r = ident(BOUFFALO)
assert r["vendor"] == "Tuya" and r["brand"] == "Tuya" and r["vendor_role"] == "brand", r
print("ok: marca a due livelli")

# --- gateway da /proc/net/route ---
route = Path(tempfile.mkdtemp()) / "route"
route.write_text("Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\n"
                 "eth0\t00000000\t0132A8C0\t0003\t0\t0\t0\t00000000\n"
                 "eth0\t0032A8C0\t00000000\t0001\t0\t0\t0\t00FFFFFF\n", encoding="ascii")
assert identity.default_gateway(str(route)) == "192.168.50.1"
assert identity.default_gateway(str(route.with_name("nope"))) is None
print("ok: gateway")

# --- mDNS TXT ---
txt = '"model=iPhone15,2" "osxvers=22" "foo=bar"'
assert scanner.parse_mdns_txt(txt) == {"model": "iPhone15,2"}
assert scanner.parse_mdns_txt('"am=AppleTV6,2" "md=Other"') == {"model": "AppleTV6,2"}
assert scanner.parse_mdns_txt('"md=Chromecast" "mf=Google"') == {"model": "Chromecast", "manufacturer": "Google"}
print("ok: mdns txt")

# --- batteria ---
assert identity.battery_assess(api=True) == ("yes", "api")
assert identity.battery_assess(api=False, scan="yes") == ("no", "api")
assert identity.battery_assess(scan="yes") == ("yes", "scan")
assert identity.battery_assess(texts=["SHHT-1"]) == ("yes", "hint")
assert identity.battery_assess(texts=["Smart-UPS 1500"]) == ("yes", "hint")
assert identity.battery_assess(texts=["SHSW-1"]) == (None, None)  # relay a rete: ignoto, non "no"
assert identity.battery_assess(model_class="mobile") == ("yes", "model")
assert identity.battery_assess(model_class="fixed") == ("no", "model")
assert identity.battery_assess() == (None, None)
print("ok: batteria")

# --- mobile ---
assert brands.match_model(["iPhone15,2"]) == "mobile" and brands.match_model(["iPad13,1"]) == "mobile"
assert brands.match_model(["MacBookPro18,1"]) == "laptop"
assert brands.match_model(["Macmini9,1"]) == "fixed" and brands.match_model(["AudioAccessory5,1"]) == "fixed"
assert brands.match_model(["Shelly1"]) is None


def mob(mac=None, **kw):
    kw.setdefault("name_is_mobile", False)
    kw.setdefault("has_ports", None)
    return identity.mobile_assess(mac=mac, **kw)


assert mob(model_class="mobile")["mobile"]                      # iPhone dal modello
assert not mob(model_class="fixed", churn=30)["mobile"]         # Mac mini / HomePod
assert not mob(churn=14)["mobile"]                              # la sola presenza non basta
assert mob(PRIVATE, churn=14)["mobile"]                         # presenza + MAC privato
assert mob(model_class="laptop", churn=6)["mobile"]             # portatile che entra e esce
assert not mob(model_class="laptop")["mobile"]                  # portatile mai visto muoversi: serve altro
# sensore Shelly a batteria: si sveglia e scompare di continuo ma e' FISSO
assert not mob(PRIVATE, churn=40, battery="yes", battery_source="api")["mobile"]
assert not mob(PRIVATE, churn=40, battery="yes", battery_source="hint", name_is_mobile=False)["mobile"]
# il telefono ha la batteria ma e' mobile (fonte "model")
assert mob(PRIVATE, model_class="mobile", battery="yes", battery_source="model")["mobile"]
assert mob(name_is_mobile=True)["mobile"]                       # "Xiaomi-14"
print("ok: mobile")

# --- presenza: transizioni in 7 giorni ---
hist = History(Path(tempfile.mkdtemp()) / "t.db")
now = 1_000_000.0
for i in range(14):
    hist.record_presence("phone", "10.0.0.5", None, i % 2 == 0, now - i * 3600)
hist.record_presence("nas", "10.0.0.6", None, True, now - 5 * 86400)
hist.record_presence("old", "10.0.0.7", None, True, now - 30 * 86400)
flaps = hist.presence_flaps(now - 7 * 86400)
assert flaps == {"phone": 14, "nas": 1}, flaps
print("ok: presenza")
print("TUTTO OK")
