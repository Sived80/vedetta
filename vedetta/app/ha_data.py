"""Dati per la dashboard in stile Home Assistant (/ha): tipo di dispositivo
dedotto, formato compatto per la UI, riepilogo, registro eventi.

Le funzioni di calcolo sono pure (prendono dizionari, restituiscono
dizionari): si provano da sole (tests/check_ha_api.py) senza avviare il
servizio. Le chiamate HTTP stanno in routes_ha.py."""
import json
import re
from pathlib import Path

from . import devices_config, i18n
from .history import History, history

# Ordine in cui la UI mostra i gruppi per tipo.
TYPE_ORDER = ("router", "server", "pc", "phone", "media", "audio", "iot", "printer", "generic")
# Clima, elettrodomestici, energia, sicurezza, aperture e acqua sono apparecchi smart di casa: un solo
# gruppo ("iot"); il tipo preciso resta nell'icona (data/device_kinds.json).
_MERGED_GROUPS = {"climate": "iot", "appliance": "iot", "energy": "iot", "security": "iot", "cover": "iot", "water": "iot"}

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_PORT_RE = re.compile(r"^\s*(\d+)")

# Regole generiche per parola chiave: "subs" = sottostringhe (parole lunghe),
# "toks" = parole intere (quelle corte, per non scattare dentro altre parole),
# "ports" = porte TCP tipiche. Il testo analizzato e' nome + marca + info
# raccolte dalle scansioni + etichette delle porte: nessun caso particolare
# per un singolo dispositivo.
_RULES = {
    # Luci, prese, interruttori e sensori IoT: un'unica categoria.
    "iot": {
        "subs": ("meross", "yeelight", "tradfri", "lightbulb", "dimmer",
                 "relay", "interruttore", "sensor"),
        "toks": {"plug", "light", "lights", "lamp", "luce", "lampada", "bulb", "hue", "wiz", "tapo", "kasa", "presa",
                 "esp32", "esp8266", "sensore"},
        "ports": set(),
    },
    "printer": {
        "subs": ("printer", "stampante", "laserjet", "officejet", "deskjet", "epson", "brother",
                 "lexmark", "ricoh", "xerox", "kyocera", "pixma"),
        "toks": {"ipp", "cups", "jetdirect", "canon"},
        "ports": {631, 9100},
    },
    # Media: TV e streaming, telecamere (TVCC) e videoregistratori (NVR/DVR).
    "media": {
        "subs": ("television", "bravia", "chromecast", "smarttv", "smart tv", "appletv", "apple tv", "firetv",
                 "fire tv", "android tv", "roku", "webos", "tizen", "hisense", "vizio",
                 "ipcam", "ip camera", "ipcamera", "webcam", "cctv", "videosorveglianza", "telecamera", "doorbell",
                 "onvif", "networkvideotransmitter"),
        "toks": {"tv", "televisore", "cam", "nvr", "dvr", "tvcc", "rtsp"},  # "camera" no: in italiano e' anche la stanza
        "ports": {554},
    },
    "audio": {
        "subs": ("speaker", "sonos", "soundbar", "homepod", "echo dot", "google home", "nest mini",
                 "nest audio", "denon", "marantz", "harman", "audio", "yamaha", "spotify", "airplay"),
        "toks": {"echo", "alexa", "bose", "hifi", "avr", "amp"},
        "ports": set(),
    },
    "router": {
        "subs": ("router", "fritz", "mikrotik", "openwrt", "unifi", "ubiquiti", "access point",
                 "repeater", "extender", "netgear", "zyxel", "draytek", "keenetic"),
        "toks": {"wlan"},
        "ports": set(),
    },
    "pc": {
        "subs": ("windows", "macbook", "laptop", "desktop", "notebook", "imac", "thinkpad", "surface", "macos",
                 "mac mini", "workstation", "chromebook", "latitude", "inspiron", "pavilion"),
        "toks": {"pc", "mac", "dell", "lenovo"},
        "ports": set(),
    },
    "server": {
        "subs": ("proxmox", "synology", "qnap", "truenas", "unraid", "docker", "raspberry", "raspbian",
                 "ubuntu", "debian", "home assistant", "homeassistant", "openmediavault"),
        "toks": {"nas", "vm", "lxc", "server"},
        "ports": {22, 2049, 3306, 5432, 6379, 8006, 8123, 27017, 1433},
    },
}
_PC_PORTS = {3389, 445, 139}


def _blob(device: dict) -> tuple[str, set[str], set[int]]:
    """Testo (minuscolo), insieme di parole e numeri di porta del dispositivo."""
    # Un nome costruito dall'app ("Apple phone") non e' un indizio: sarebbe l'app che si da' ragione da sola.
    parts = [None if device.get("name_generated") else device.get("name"), device.get("brand"), device.get("vendor")]
    # Il sistema operativo ("Linux 4.14", "Windows 10") non e' un ruolo: gira su telefoni, TV,
    # router, telecamere e server. Conta come indizio debole, a parte (vedi type_scores).
    parts += [v for k, v in (device.get("extra") or {}).items() if isinstance(v, str)]
    ports: set[int] = set()
    for p in device.get("scanned_ports") or []:
        label = p.get("label") or ""
        parts.append(label)
        m = _PORT_RE.match(label)
        if m:
            ports.add(int(m.group(1)))
    text = " ".join(str(p) for p in parts if p).lower()
    return text, set(_TOKEN_RE.findall(text)), ports


def _hit(rule: dict, text: str, tokens: set[str], ports: set[int]) -> bool:
    return (any(s in text for s in rule["subs"]) or bool(tokens & rule["toks"]) or bool(ports & rule["ports"]))


# ---- categoria a punteggio --------------------------------------------------
# Ogni indizio da' punti a una o piu' categorie, con un peso che dipende da quanto e'
# affidabile; vince la categoria con piu' punti (a parita', l'ordine di TYPE_ORDER),
# sotto MIN_TYPE_SCORE il dispositivo resta "generic". Nessuna regola per una marca:
# contano ruoli di rete, protocolli dichiarati, servizi verificati, porte e parole.
W_ROLE, W_DECLARED, W_SERVICE, W_PORT_GUESS, W_WORD, W_BRAND = 10, 8, 4, 1, 2, 3
MIN_TYPE_SCORE = 2
W_PLATFORM_MAX = 3
_PLATFORM_KINDS = {"microcontroller", "bluetooth"}   # tipi che dicono solo la piattaforma hardware

# Servizi mDNS dichiarati (DNS-SD) -> (categoria, peso)
_MDNS_TYPE = {
    "_googlecast._tcp": ("media", W_DECLARED), "_androidtvremote2._tcp": ("media", W_DECLARED),
    "_amzn-wplay._tcp": ("media", W_DECLARED),
    "_ipp._tcp": ("printer", W_DECLARED), "_ipps._tcp": ("printer", W_DECLARED),
    "_printer._tcp": ("printer", W_DECLARED), "_pdl-datastream._tcp": ("printer", W_DECLARED),
    "_sonos._tcp": ("audio", W_DECLARED), "_raop._tcp": ("audio", 2), "_spotify-connect._tcp": ("audio", 1),
    "_esphomelib._tcp": ("iot", 6), "_workstation._tcp": ("pc", 4), "_rdp._tcp": ("pc", 4),
    "_smb._tcp": ("server", 2), "_mqtt._tcp": ("server", 3), "_home-assistant._tcp": ("server", 6),
}
# Tipi UPnP dichiarati -> (categoria, peso)
_UPNP_TYPE = {
    "MediaRenderer": ("media", W_DECLARED), "dial": ("media", W_DECLARED),
    "InternetGatewayDevice": ("router", W_DECLARED), "WFADevice": ("router", W_DECLARED),
    "WLANAccessPointDevice": ("router", W_DECLARED), "MediaServer": ("server", 2), "Printer": ("printer", W_DECLARED),
}
# Interfaccia locale che ha risposto -> (categoria, peso)
# Tasmota ed ESPHome sono firmware generici (luce, presa, sensore, termostato...): pochi punti,
# cosi' il nome o il servizio del dispositivo decidono.
_API_TYPE = {"shelly": ("iot", W_DECLARED), "tasmota": ("iot", 2), "esphome": ("iot", 3),
             "cast": ("media", W_DECLARED), "roku": ("media", W_DECLARED), "sonos": ("audio", W_DECLARED)}
# Porte tipiche -> categoria (verificata da nmap: W_SERVICE; solo numero: W_PORT_GUESS)
_PORT_TYPE = {
    554: "media", 1935: "media", 8008: "media", 8009: "media", 7000: "media", 8060: "media",
    631: "printer", 9100: "printer", 515: "printer",
    3389: "pc", 5900: "pc",
    22: "server", 8006: "server", 8123: "server", 2049: "server", 3306: "server", 5432: "server",
    6379: "server", 27017: "server", 1433: "server", 9000: "server",
    1883: "iot", 8883: "iot", 5683: "iot", 6053: "iot",
    1400: "audio",
}
# Porte comuni a piu' categorie (SMB: PC, NAS e router con USB; FTP; DNS): poco peso a tutte.
_PORT_SHARED = {139: ("pc", "server"), 445: ("pc", "server"), 21: ("server",), 53: ("server", "router")}


# ---- tipi di dispositivo di casa (data/device_kinds.json): gruppo + icona + parole generiche
_kinds_cache: list | None = None


def _kinds() -> list[dict]:
    """Tipi caricati dal file. Le parole corte (una parola, fino a 7 lettere) contano solo
    come parola intera, con il plurale: "light" non vale dentro "lighttpd"."""
    global _kinds_cache
    if _kinds_cache is None:
        try:
            raw = json.loads((Path(__file__).resolve().parent / "data" / "device_kinds.json").read_text(encoding="utf-8"))["kinds"]
        except (OSError, ValueError, KeyError):
            raw = []
        out = []
        for k in raw:
            subs, toks = [], set(k.get("tokens") or [])
            for w in k.get("words") or []:
                w = w.lower()
                if " " not in w and "-" not in w and len(w) <= 7:
                    toks.add(w)
                else:
                    subs.append(w)
            toks |= {t + "s" for t in list(toks)}
            out.append({"id": k["id"], "group": _MERGED_GROUPS.get(k["group"], k["group"]), "icon": k["icon"], "subs": subs, "toks": toks,
                        "w": int(k.get("w", 2)), "mdns": set(k.get("mdns") or []), "upnp": set(k.get("upnp") or []),
                        "brands": set(k.get("brands") or []), "product": bool(k.get("product"))})
        _kinds_cache = out
    return _kinds_cache


_ha_table_cache: dict | None = None


def _ha_integrations() -> dict:
    global _ha_table_cache
    if _ha_table_cache is None:
        try:
            _ha_table_cache = json.loads((Path(__file__).resolve().parent / "data" / "ha_integrations.json").read_text(encoding="utf-8"))["integrations"]
        except (OSError, ValueError, KeyError):
            _ha_table_cache = {}
    return _ha_table_cache


# Famiglie di indizi: lo stesso fatto raccontato da piu' segnali (Cast = servizio mDNS + interfaccia + porte 8008/8009 +
# DIAL) conta UNA volta, con il punteggio piu' alto della famiglia. Le parole nel testo (regole e tipi) sono un'unica
# famiglia per categoria. Le porte, in totale, non superano W_PORTS_MAX per categoria.
_FAMILY_SERVICE = {"_googlecast._tcp": "cast", "_androidtvremote2._tcp": "androidtv"}
_FAMILY_UPNP = {"dial": "cast"}
_FAMILY_PORT = {8008: "cast", 8009: "cast"}
W_PORTS_MAX = 6
MARGIN_BELOW = 5   # sotto questo punteggio, due categorie alla pari non si spareggiano: "generic"


def type_evidence(device: dict, adapter: str | None = None, kinds_out: dict | None = None) -> list[dict]:
    """Tutti gli indizi di categoria: [{"group", "family", "pts", "source"}]. Da qui type_scores ricava i punti
    (una volta per famiglia) e la modalita' debug mostra cosa ha deciso."""
    from . import roles, signatures  # tardivi: roles importa moduli di rete
    ev: list[dict] = []

    def add(group: str, pts: int, family: str, source: str) -> None:
        ev.append({"group": _MERGED_GROUPS.get(group, group), "family": family, "pts": pts, "source": source})

    ip = device.get("ip")
    upnp_types = roles.upnp_types(ip)
    # Piattaforme IoT (Shelly, Tasmota, ESPHome, chip Espressif...): dicono "e' un apparecchio smart", non cosa fa.
    # Valgono poco e in totale (W_PLATFORM_MAX): una parola che dice la funzione vince sempre.
    platform = 0
    if adapter and adapter.startswith("shelly"):
        platform += W_ROLE  # risposta della sua API diretta
    if {"gateway", "router", "ap", "repeater"} & set(roles.roles_for(ip)):
        add("router", W_ROLE, "role", "ruolo di rete")
    extra = device.get("extra") or {}
    services = [s for s in (extra.get("mdns_services") or "").replace(" ", "").split(",") if s]
    for svc in services:
        if svc in _MDNS_TYPE:
            group, pts = _MDNS_TYPE[svc]
            add(group, pts, _FAMILY_SERVICE.get(svc, "svc:" + svc), "mDNS " + svc)
    for upnp in upnp_types:
        if upnp in _UPNP_TYPE:
            group, pts = _UPNP_TYPE[upnp]
            add(group, pts, _FAMILY_UPNP.get(upnp, "upnp:" + upnp), "UPnP " + upnp)
    if extra.get("api_source") in _API_TYPE:
        kind_api, pts_api = _API_TYPE[extra["api_source"]]
        if kind_api == "iot":
            platform += pts_api
        else:
            add(kind_api, pts_api, "cast" if extra["api_source"] == "cast" else "api:" + extra["api_source"], "API " + extra["api_source"])
    if any(extra.get(k) for k in ("onvif_name", "onvif_hardware", "onvif_manufacturer")) \
            or "NetworkVideoTransmitter" in (extra.get("wsd_types") or ""):
        add("media", W_DECLARED, "onvif", "ONVIF")
    if extra.get("rtsp_server"):
        add("media", 6, "rtsp", "RTSP")
    for p in device.get("scanned_ports") or []:
        m = _PORT_RE.match(p.get("label") or "")
        port = int(m.group(1)) if m else None
        kind = _PORT_TYPE.get(port)
        if kind:
            fam = _FAMILY_PORT.get(port)
            # la porta Cast e' nella famiglia Cast (conta una volta con servizio e API); le altre sono famiglie "porta"
            add(kind, W_SERVICE if p.get("confirmed") else W_PORT_GUESS, fam or "port:%s" % port, "porta %s" % port)
        for shared in _PORT_SHARED.get(port, ()):
            add(shared, W_PORT_GUESS, "port:%s:%s" % (port, shared), "porta %s" % port)
    text, tokens, ports = _blob(device)
    for kind, rule in _RULES.items():
        if any(s in text for s in rule["subs"]) or tokens & rule["toks"]:
            add(kind, W_WORD, "words", "parola nel testo")
    # Marca del prodotto (o produttore del MAC se vende solo apparecchi di quel tipo); conta anche il nome (un PC
    # chiamato "MSI"): il produttore del MAC e' spesso solo la scheda di rete, il nome lo sceglie chi installa il sistema.
    brand_tokens = set(_TOKEN_RE.findall(" ".join(filter(None, [
        device.get("brand"), device.get("name"),
        device.get("vendor") if device.get("vendor_role") == "brand" else None])).lower()))
    # Integrazioni di Home Assistant agganciate al dispositivo: dichiarano cos'e' (onvif, braviatv...).
    for dom in ((device.get("ha_registry") or {}).get("domains") or []):
        entry = _ha_integrations().get(dom)
        if entry and entry.get("platform"):
            platform += W_PLATFORM_MAX
        elif entry:
            add(entry["group"], W_DECLARED, "ha", "integrazione HA " + dom)
        if entry and entry.get("kind") and kinds_out is not None:
            kinds_out[entry["kind"]] = kinds_out.get(entry["kind"], 0) + W_DECLARED
    declared_svc = set(services)
    declared_upnp = set(upnp_types)
    for kd in _kinds():
        pts = 0
        if any(s in text for s in kd["subs"]) or tokens & kd["toks"]:
            word_pts = kd["w"]
            pts += word_pts
            if kd["id"] not in _PLATFORM_KINDS:
                add(kd["group"], word_pts, "words", "parola: " + kd["id"])
        for svc in sorted(declared_svc & kd["mdns"]):
            pts += W_DECLARED
            if kd["id"] not in _PLATFORM_KINDS:
                add(kd["group"], W_DECLARED, _FAMILY_SERVICE.get(svc, "svc:" + svc), "mDNS " + svc)
        for up in sorted(declared_upnp & kd["upnp"]):
            pts += W_DECLARED
            if kd["id"] not in _PLATFORM_KINDS:
                add(kd["group"], W_DECLARED, _FAMILY_UPNP.get(up, "upnp:" + up), "UPnP " + up)
        if brand_tokens & kd["brands"]:
            pts += W_BRAND
            add(kd["group"], W_BRAND, "brand", "marca: " + kd["id"])
        if pts and kd["id"] in _PLATFORM_KINDS:
            platform += pts
        elif pts and kinds_out is not None:
            kinds_out[kd["id"]] = pts
    # Firme dei prodotti (app/data/signatures.json): dove i segnali generici sono ambigui decide il modello dichiarato.
    for sig in signatures.matches({**device, "extra": extra}, upnp_types):
        add(sig["group"], int(sig.get("weight", W_ROLE)), "sig:" + sig["id"], "firma " + sig["id"])
        if sig.get("kind") and kinds_out is not None:
            kinds_out[sig["kind"]] = kinds_out.get(sig["kind"], 0) + int(sig.get("weight", W_ROLE))
    if platform:
        add("iot", min(platform, W_PLATFORM_MAX), "platform", "piattaforma IoT")
    # Solo porte IoT (MQTT, CoAP) e nient'altro: un dispositivo embedded.
    if ports and ports <= {1883, 8883, 5683}:
        add("iot", 3, "port:iot", "solo porte IoT")
    return ev


def _aggregate(ev: list[dict]) -> dict[str, int]:
    """Punti per categoria: per ogni famiglia il valore piu' alto, le famiglie si sommano; le porte hanno un tetto."""
    best: dict[tuple, int] = {}
    for e in ev:
        key = (e["group"], e["family"])
        best[key] = max(best.get(key, 0), e["pts"])
    scores: dict[str, int] = {}
    port_total: dict[str, int] = {}
    for (group, family), pts in best.items():
        if family.startswith("port:"):
            port_total[group] = port_total.get(group, 0) + pts
        else:
            scores[group] = scores.get(group, 0) + pts
    for group, pts in port_total.items():
        scores[group] = scores.get(group, 0) + min(pts, W_PORTS_MAX)
    return scores


def type_scores(device: dict, adapter: str | None = None, kinds_out: dict | None = None) -> dict[str, int]:
    """Punti per categoria (vedi sopra), per capire e per i test. kinds_out (opzionale)
    si riempie con i punti per ogni tipo di dispositivo, da cui si sceglie l'icona."""
    return _aggregate(type_evidence(device, adapter, kinds_out))


def icon_for(device: dict, adapter: str | None = None, kind: str | None = None) -> str | None:
    """Nome dell'icona MDI piu' adatta al dispositivo: quella del tipo (data/device_kinds.json)
    con piu' punti dentro la categoria scelta; None = icona della categoria."""
    group = kind or infer_type(device, adapter)
    kinds_out: dict[str, int] = {}
    type_scores(device, adapter, kinds_out)
    best, best_pts = None, 0
    for kd in _kinds():
        if kd["group"] != group:
            continue
        pts = kinds_out.get(kd["id"], 0)
        if pts > best_pts:
            best, best_pts = kd["icon"], pts
    return best


def kind_is_product(kind_id: str | None) -> bool:
    """True per i tipi che sono un prodotto preciso (Home Assistant, Raspberry Pi): il nome
    e' il tipo stesso, senza marca davanti."""
    return any(kd["id"] == kind_id and kd.get("product") for kd in _kinds())


def best_kind(device: dict, adapter: str | None = None) -> str | None:
    """Id del tipo di dispositivo (data/device_kinds.json) con piu' punti, nella categoria scelta."""
    group = infer_type(device, adapter)
    kinds_out: dict[str, int] = {}
    type_scores(device, adapter, kinds_out)
    best, best_pts = None, 0
    for kd in _kinds():
        if kd["group"] == group and kinds_out.get(kd["id"], 0) > best_pts:
            best, best_pts = kd["id"], kinds_out[kd["id"]]
    return best


def infer_type(device: dict, adapter: str | None = None) -> str:
    """Categoria del dispositivo a punteggio (type_scores). Il flag is_mobile (scelta
    dell'utente o punteggio "mobile" del probe) vince su tutto."""
    if device.get("is_mobile"):
        return "phone"
    scores = type_scores(device, adapter)
    if not scores:
        return "generic"
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], TYPE_ORDER.index(kv[0]) if kv[0] in TYPE_ORDER else 99))
    best = ranked[0]
    if best[1] < MIN_TYPE_SCORE:
        return "generic"
    # Due categorie alla pari con indizi deboli: non si sceglie a caso (come Nmap quando i due migliori sono vicini).
    if len(ranked) > 1 and best[1] < MARGIN_BELOW and ranked[1][1] >= MIN_TYPE_SCORE and best[1] - ranked[1][1] < 1:
        return "generic"
    return best[0]


def effective_type(device: dict, cfg: dict | None = None) -> str:
    """Categoria scelta a mano (cfg["type_user"]) oppure quella a punteggio."""
    cfg = cfg or {}
    chosen = cfg.get("type_user")
    if chosen in TYPE_ORDER or chosen == "generic":
        return chosen
    return infer_type(device, cfg.get("adapter"))


# ---- configurazione (adapter, scelta "mobile") con cache sul file ----
_cfg_cache: dict = {"mtime": None, "map": {}}


def config_map() -> dict[str, dict]:
    """{id: configurazione} da devices.yaml, riletta solo se il file cambia
    (serve a conoscere adapter e scelta manuale di ogni dispositivo senza
    leggere il disco a ogni evento)."""
    try:
        mtime = devices_config.DEVICES_PATH.stat().st_mtime
    except OSError:
        return {}
    if _cfg_cache["mtime"] != mtime:
        try:
            _cfg_cache["map"] = {d["id"]: d for d in devices_config.load_devices()}
            _cfg_cache["mtime"] = mtime
        except Exception:
            return _cfg_cache["map"]
    return _cfg_cache["map"]


def _signal(device: dict) -> dict | None:
    kind, value = device.get("signal_kind"), device.get("signal_value")
    if kind not in ("wifi", "lan") or value is None:
        return None
    quality = device.get("signal_label")
    band = device.get("signal_band")
    if kind == "wifi":
        display = f"{value} dBm" + (f" · {band}" if band else "")
    else:
        display = str(value)
    return {
        "kind": kind, "value": value, "band": band, "display": display,
        "quality": quality, "text": i18n.t("signal." + quality) if quality else None,
        "color": device.get("signal_color"),
    }


def compact_device(device: dict, cfg: dict | None = None) -> dict:
    """Dispositivo dello stato condiviso -> formato compatto per la UI /ha.
    Testi e nomi dei campi nella lingua corrente (i18n.use)."""
    cfg = cfg or {}
    extra = device.get("extra") or {}
    _t = effective_type(device, cfg)
    mobile_cfg = cfg.get("mobile")
    online = bool(device.get("online"))
    return {
        "id": device["id"],
        "name": device.get("name") or device.get("ip"),
        "ip": device.get("ip"),
        "port": device.get("port", 80),
        "mac": device.get("mac"),
        # Due livelli: vendor = produttore del MAC (chip/scheda), brand = marca del
        # prodotto (None se non nota); brand_source/confidence dicono da dove viene.
        "vendor": device.get("vendor"),
        "vendor_role": device.get("vendor_role"),
        "brand": device.get("brand"),
        "brand_source": device.get("brand_source"),
        "brand_confidence": device.get("brand_confidence"),
        "brand_evidence": device.get("brand_evidence"),
        "brand_declared": device.get("brand_declared"),
        # battery: "yes" | "no" | None (ignoto), con la fonte; un apparecchio di rete
        # a batteria (sensore) non e' "mobile".
        "battery": device.get("battery"),
        "battery_source": device.get("battery_source"),
        "type": _t,
        "icon": icon_for(device, cfg.get("adapter"), _t),
        "is_mobile": bool(device.get("is_mobile")),
        # "auto" = decide il nome/le scansioni; "yes"/"no" = scelta fatta a mano.
        "mobile_mode": "auto" if mobile_cfg is None else ("yes" if mobile_cfg else "no"),
        "name_source": cfg.get("name_source"),
        "wol_ok": bool(cfg.get("wol_ok")),
        "ha_share": bool(cfg.get("ha_share")),
        "type_user": cfg.get("type_user"),
        "brand_user": cfg.get("brand_user"),
        "online": online,
        "last_seen": None if online else device.get("last_seen"),
        "uptime": device.get("uptime"),
        "signal": _signal(device),
        "latency_ms": device.get("latency_ms"),
        "latency_color": device.get("latency_color"),
        "ports": [
            {"label": p.get("label"), "category": p.get("category") or "other", "confirmed": bool(p.get("confirmed"))}
            for p in device.get("scanned_ports") or []
        ],
        "url": device.get("url"),
        "title": extra.get("title"),
        "scanned_at": device.get("scanned_at"),
        "attrs": [
            {"key": k, "label": i18n.t_or("extra." + k, k), "value": str(v)}
            for k, v in extra.items() if k not in ("vendor", "brand") and v not in (None, "")
        ],
    }


def compact_all(devices: list[dict]) -> list[dict]:
    cfg = config_map()
    return [compact_device(d, cfg.get(d["id"])) for d in devices]


def _avg_latency(devices: list[dict]) -> int | None:
    vals = [d["latency_ms"] for d in devices if d.get("online") and d.get("latency_ms") is not None]
    return round(sum(vals) / len(vals)) if vals else None


def build_summary(devices: list[dict], poll: dict, activity: dict, new_devices: dict, rev: int = 0) -> dict:
    """Conteggi, marche, tipi e stato della ricerca. Prende i dispositivi
    dello stato condiviso (non compatti): e' pura, senza accesso al disco."""
    online = sum(1 for d in devices if d.get("online"))
    mobile = [d for d in devices if d.get("is_mobile")]
    brands: dict[str | None, int] = {}
    chips: dict[str, int] = {}  # produttore del MAC dei dispositivi senza marca nota
    types: dict[str, int] = {}
    cfg = config_map()
    for d in devices:
        brand = d.get("brand") or None  # la marca del PRODOTTO, mai il produttore della scheda
        brands[brand] = brands.get(brand, 0) + 1
        if brand is None:
            chip = d.get("vendor") or None
            if chip:
                chips[chip] = chips.get(chip, 0) + 1
        kind = effective_type(d, cfg.get(d["id"]))
        types[kind] = types.get(kind, 0) + 1
    brand_list = sorted(
        ({"brand": b, "count": n} for b, n in brands.items()),
        key=lambda r: (-r["count"], r["brand"] is None, (r["brand"] or "").lower()),
    )
    total = len(devices)
    return {
        "rev": rev,
        "total": total,
        "online": online,
        "offline": total - online,
        "online_pct": round(100 * online / total, 1) if total else None,
        "mobile": len(mobile),
        "mobile_online": sum(1 for d in mobile if d.get("online")),
        "brands": brand_list,
        "unknown_chips": sorted(({"vendor": v, "count": n} for v, n in chips.items()),
                                key=lambda r: (-r["count"], r["vendor"].lower())),
        "battery": sum(1 for d in devices if d.get("battery") == "yes"),
        "types": {k: types[k] for k in TYPE_ORDER if k in types},
        # Tempo di risposta medio dei dispositivi online che lo hanno misurato.
        "latency_avg_ms": _avg_latency(devices),
        "poll": {
            "interval_ms": poll.get("interval_ms"), "next_in_ms": poll.get("next_in_ms"),
            "paused": bool(poll.get("paused")), "paused_in_ms": poll.get("paused_in_ms"),
        },
        "activity": {"search": bool(activity.get("search")), "rescanning": list(activity.get("rescanning") or [])},
        "new_devices": {"count": new_devices.get("count", 0), "devices": new_devices.get("devices", [])},
    }


# ---- registro eventi (logbook) ----
def recent_presence(limit: int, hist: History = history) -> list[dict]:
    """Ultimi eventi online/offline dello storico, i piu' recenti per primi.
    Legge presence_events senza toccare history.py (stessa connessione e lo
    stesso lock degli altri metodi)."""
    limit = max(1, min(int(limit), 200))
    with hist._lock:
        rows = hist._db.execute(
            "SELECT id, device_id, ip, online, ts FROM presence_events ORDER BY ts DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [{"id": r["id"], "device_id": r["device_id"], "ip": r["ip"], "online": bool(r["online"]), "ts": r["ts"]}
            for r in rows]


def logbook_entries(rows: list[dict], devices: dict[str, dict], cfg: dict[str, dict] | None = None) -> list[dict]:
    """Eventi grezzi + nome e tipo del dispositivo (se non c'e' piu' in
    configurazione resta l'ultimo IP noto) + frase nella lingua corrente."""
    cfg = cfg or {}
    out = []
    for r in rows:
        d = devices.get(r["device_id"])
        out.append({
            "id": r["id"],
            "device_id": r["device_id"],
            "name": (d.get("name") if d else None) or r.get("ip") or r["device_id"],
            "ip": r.get("ip"),
            "type": effective_type(d, cfg.get(r["device_id"])) if d else "generic",
            "dev_icon": icon_for(d, (cfg.get(r["device_id"]) or {}).get("adapter")) if d else None,
            "known": d is not None,
            "online": r["online"],
            "ts": r["ts"],
            "message": i18n.t("ha.logbook.online" if r["online"] else "ha.logbook.offline"),
        })
    return out


def slim_history(window: dict) -> dict:
    """Finestra di history.presence_segments con i tempi a secondo intero:
    meno byte nelle risposte che coprono tutti i dispositivi."""
    return {
        "from": int(window["from"]), "to": int(window["to"]),
        "segments": [{"from": int(s["from"]), "to": int(s["to"]), "online": s["online"]} for s in window["segments"]],
        "online_pct": window["online_pct"],
    }
