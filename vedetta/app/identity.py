"""Identita' di un dispositivo in un solo punto: marca del prodotto, "mobile" e
batteria. Lo usa probe.py. Principio comune (lo stesso di Fing, Fingerbank e delle
integrazioni di Home Assistant): niente verdetto da un solo indizio, ma piu'
evidenze, ognuna con una fonte e una confidenza, e le fonti dirette del
dispositivo battono quelle indirette.

MARCA. Il prefisso MAC (OUI) e' il produttore della SCHEDA, non del prodotto: vedi
brands.py (vendor_roles: component, virtual, dual, brand). Qui si espone il
risultato a due livelli:
  vendor            produttore del prefisso MAC (chip/scheda), ripulito
  vendor_role       component | virtual | dual | brand | private (MAC casuale) | None
  brand             marca del prodotto, None se non nota (mai il chip!)
  brand_source      dhcp | name | web | declared | oui | None
  brand_confidence  high | medium | low | None
  brand_evidence    confirmed | plausible | None (non determinata). Confermata solo
                    quando il dispositivo l'ha DICHIARATA (UPnP/mDNS/ONVIF), quando il
                    prefisso MAC reale e' di una marca; ogni deduzione (nome, web, DHCP)
                    resta plausibile.
  brand_declared    valore dichiarato dal dispositivo che non e' una marca nota
                    (es. "IPCAM" di una telecamera white-label): "nessuna marca
                    dichiarata", da non confondere con "non determinata".
Il gateway di rete (dual + gateway = router della sua marca) e' l'unica
conferma "di rete" per i produttori ambigui come TP-Link.

MOBILE. "Mobile" = telefono, tablet, portatile: un oggetto che segue una persona.
Punteggio a somma, soglia MOBILE_THRESHOLD (3); la scelta manuale dell'utente
(devices.yaml "mobile") vince sempre, la decide probe.py:
  +3 nome da telefono / impronta DHCP iOS / hostname iphone-ipad  (dhcp.mobile_score)
  +2 impronta DHCP Android (serve un secondo indizio), +1 MAC privato (+1 senza porte)
  -2 impronta Windows/macOS/Linux (dhcp.mobile_score)
  +3 modello mobile (iPhone15,2, iPad, SM-xxxx), +2 portatile (MacBook), -3 fisso (Mac mini, HomePod)
  +1/+2 presenza: 6/14 o piu' transizioni online/offline in 7 giorni (i telefoni
      entrano e escono dalla rete, le apparecchiature fisse no); da sola non basta
  -4 batteria di rete (sensore Shelly, UPS): e' a batteria ma FISSO, non mobile.
  -4 riceve o riproduce video (mDNS Chromecast/Android TV/Whisperplay, UPnP MediaRenderer o
      DIAL, servizio o sistema "TV" riconosciuto da nmap): TV, chiavetta, box.
  +2 "Android" nel nome: e' il sistema, non il tipo (serve un secondo indizio).
  +3 servizio mDNS che solo i telefoni annunciano (Android Nearby, sincronizzazione iOS).
  +1 nessuna porta in ascolto, ma solo se c'e' gia' un altro indizio.

BATTERIA. Attributo battery = yes | no | None (ignoto) con battery_source:
  api     risposta del dispositivo: Shelly Gen1 /status campo "bat", Gen2
          Shelly.GetStatus componente "devicepower:0"
  scan    lo stesso dato salvato dall'ultima scansione
  hint    testo (modello, SNMP, titolo web) riconosciuto da "battery_hints" (UPS, sensori)
  model   telefono/portatile dal modello (batteria, ma anche mobile) o apparecchio fisso (no)
"""
import time

from . import brands, dhcp
from .vendor_lookup import is_private_mac, lookup_vendor
from .brands import normalize_brand

MOBILE_THRESHOLD = 3
CHURN_WINDOW_DAYS = 7
CHURN_REFRESH_S = 600
_CHURN_WEAK, _CHURN_STRONG = 6, 14

_NO_GATEWAY = object()
_gateway_cache: dict = {"value": _NO_GATEWAY}


def default_gateway(route_path: str = "/proc/net/route") -> str | None:
    """IP del gateway predefinito (da /proc/net/route, Linux); None se non si legge.
    Si calcola una volta sola: il gateway di una LAN domestica non cambia."""
    if _gateway_cache["value"] is not _NO_GATEWAY and route_path == "/proc/net/route":
        return _gateway_cache["value"]
    gateway = None
    try:
        with open(route_path, encoding="ascii") as f:
            next(f, None)
            for line in f:
                cols = line.split()
                if len(cols) > 2 and cols[1] == "00000000" and int(cols[3], 16) & 2:
                    raw = int(cols[2], 16).to_bytes(4, "little")
                    gateway = ".".join(str(b) for b in raw)
                    break
    except (OSError, ValueError, StopIteration):
        gateway = None
    if route_path == "/proc/net/route" and gateway:
        _gateway_cache["value"] = gateway
    return gateway


def identify_brand(mac: str | None, *, names=(), upnp_manufacturer: str | None = None, declared=(),
                   web_text: str | None = None, os_family: str | None = None, is_gateway: bool = False,
                   raw_vendor: str | None = None) -> dict:
    """Marca a due livelli (vedi docstring del modulo). raw_vendor e' il nome
    grezzo di nmap/arp-scan, usato solo se il database dei prefissi non conosce il MAC."""
    vendor = lookup_vendor(mac)
    if vendor is None and raw_vendor and not is_private_mac(mac):
        vendor = normalize_brand(raw_vendor)
    found = brands.resolve(vendor, names=list(names), upnp_manufacturer=upnp_manufacturer, declared=declared,
                           web_text=web_text, os_family=os_family, is_gateway=is_gateway)
    role = found["role"] or ("private" if is_private_mac(mac) else None)
    source = found["source"]
    # Confermata anche quando la fonte scelta e' un'altra ma il dispositivo dichiara la
    # stessa marca (es. nome "SONY XR-55X92K" e UPnP manufacturer "Sony").
    declared_brands = {brands.known_brand(v) for v in (upnp_manufacturer, *declared) if v}
    if not found["brand"]:
        evidence = None
    elif source == "declared" or found["brand"] in declared_brands \
            or (source == "oui" and role == "brand" and not is_private_mac(mac))             or (role == "brand" and not is_private_mac(mac) and brands.known_brand(vendor) == found["brand"]):  # MAC e nome concordano
        evidence = "confirmed"
    else:
        evidence = "plausible"
    generic = None
    if not found["brand"]:
        generic = next((str(v).strip() for v in (upnp_manufacturer, *declared) if v and str(v).strip()), None)
    return {"vendor": vendor, "vendor_role": role, "brand": found["brand"],
            "brand_source": source, "brand_confidence": found["confidence"],
            "brand_evidence": evidence, "brand_declared": generic}


def battery_assess(*, api: bool | None = None, scan: str | None = None, texts=(),
                   model_class: str | None = None) -> tuple[str | None, str | None]:
    """(battery, fonte): dalla risposta diretta del dispositivo, poi dalla scansione
    salvata, poi dal modello, infine dagli indizi testuali. (None, None) = ignoto."""
    if api is not None:
        return ("yes" if api else "no"), "api"
    if scan in ("yes", "no"):
        return scan, "scan"
    if model_class in ("mobile", "laptop"):
        return "yes", "model"
    if model_class == "fixed":
        return "no", "model"
    hint = brands.battery_hint(texts)
    if hint:
        return hint, "hint"
    return None, None


_churn: dict = {"ts": 0.0, "data": {}}


def presence_churn(device_id: str, now: float | None = None) -> int:
    """Transizioni online/offline del dispositivo negli ultimi 7 giorni. Una sola
    query per tutti i dispositivi, rinfrescata ogni 10 minuti."""
    now = time.time() if now is None else now
    if now - _churn["ts"] > CHURN_REFRESH_S:
        try:
            from .history import history  # import tardivo: apre il database
            _churn["data"] = history.presence_flaps(now - CHURN_WINDOW_DAYS * 86400)
        except Exception:
            pass  # si tiene l'ultimo valore noto (o nessuno)
        _churn["ts"] = now
    return _churn["data"].get(device_id, 0)


def mobile_assess(*, mac: str | None, name_is_mobile: bool, has_ports: bool | None,
                  model_class: str | None = None, battery: str | None = None,
                  battery_source: str | None = None, churn: int = 0,
                  name_weak: bool = False, media_receiver: bool = False, mobile_service: bool = False) -> dict:
    """Punteggio "telefono/tablet/portatile" (vedi docstring del modulo).
    Ritorna {"mobile": bool, "score": int, "reason": indizio principale}."""
    score, reason = dhcp.mobile_score(mac, name_is_mobile, has_ports)
    if name_weak and not name_is_mobile:
        score, reason = score + 2, reason or "nome"  # "Android" nel nome: indizio debole
    if model_class == "mobile":
        score, reason = score + 3, reason if score > 0 and reason else "model"
    elif model_class == "laptop":
        score, reason = score + 2, reason if score > 0 and reason else "model"
    elif model_class == "fixed":
        score -= 3
    # L'alternanza online/offline conta solo con un MAC privato (telefoni) o un portatile
    # riconosciuto: una TV o un PC fisso, che si spengono ogni sera, hanno il MAC del produttore.
    if dhcp.is_private_mac(mac) or model_class == "laptop":
        if churn >= _CHURN_STRONG:
            score, reason = score + 2, reason or "presence"
        elif churn >= _CHURN_WEAK:
            score, reason = score + 1, reason or "presence"
    if mobile_service:
        score, reason = score + 3, reason or "servizio mobile"  # annunciato solo da telefoni e tablet
    # Nessun servizio in ascolto conferma qualunque altro indizio (i telefoni non ne hanno);
    # da solo non conta: anche molti dispositivi IoT non hanno porte.
    if has_ports is False and score > 0:
        score += 1
    if media_receiver:
        score -= 4  # riceve o riproduce video (cast, mirroring, renderer): TV, chiavetta, box
        reason = None
    if battery == "yes" and battery_source in ("api", "scan", "hint"):
        score -= 4  # a batteria ma di rete e fisso: non e' un telefono
        reason = None
    return {"mobile": score >= MOBILE_THRESHOLD, "score": score, "reason": reason if score >= MOBILE_THRESHOLD else None}
