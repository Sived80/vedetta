"""Data for the Home Assistant-style dashboard (/ha): inferred device type,
compact format for the UI, summary, event log.

The calculation functions are pure (they take dicts and return
dicts): they can be tested on their own (tests/check_ha_api.py) without starting the
service. The HTTP calls live in routes_ha.py."""
import json
import re
from pathlib import Path

from . import brand_logo, devices_config, i18n
from .history import History, history

# Order in which the UI shows the groups by type.
TYPE_ORDER = ("router", "server", "pc", "phone", "media", "audio", "iot", "printer", "generic")
# Climate, appliances, energy, security, openings and water are smart home devices: a single
# group ("iot"); the precise type stays in the icon (data/device_kinds.json).
_MERGED_GROUPS = {"climate": "iot", "appliance": "iot", "energy": "iot", "security": "iot", "cover": "iot", "water": "iot"}

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_PORT_RE = re.compile(r"^\s*(\d+)")

# Generic keyword rules: "subs" = substrings (long words),
# "toks" = whole words (the short ones, so they do not fire inside other words),
# "ports" = typical TCP ports. The analyzed text is name + brand + info
# collected by the scans + port labels: no special case
# for a single device.
_RULES = {
    # Lights, plugs, switches and IoT sensors: a single category.
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
    # Media: TV and streaming, cameras (CCTV) and video recorders (NVR/DVR).
    "media": {
        "subs": ("television", "bravia", "chromecast", "smarttv", "smart tv", "appletv", "apple tv", "firetv",
                 "fire tv", "android tv", "roku", "webos", "tizen", "hisense", "vizio",
                 "ipcam", "ip camera", "ipcamera", "webcam", "cctv", "videosorveglianza", "telecamera", "doorbell",
                 "onvif", "networkvideotransmitter"),
        "toks": {"tv", "televisore", "cam", "nvr", "dvr", "tvcc", "rtsp"},  # not "camera": in Italian it is also the room
        "ports": {554},
    },
    "audio": {
        "subs": ("speaker", "sonos", "soundbar", "homepod", "echo dot", "google home", "nest mini",
                 "nest audio", "denon", "marantz", "harman", "audio", "yamaha"),
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
    """Text (lowercase), set of words and port numbers of the device."""
    # A name built by the app ("Apple phone") is not a clue: the app would just be agreeing with itself.
    parts = [None if device.get("name_generated") else device.get("name"), device.get("brand"), device.get("vendor")]
    # The operating system ("Linux 4.14", "Windows 10") is not a role: it runs on phones, TVs,
    # routers, cameras and servers. It counts as a weak clue, separately (see type_scores).
    # What Home Assistant says about the device (ha_*: area, model, integration) is not what the device says about itself: the
    # integrations are counted apart, by their own table. ("mikrotik_router" as a word made every device tracked by it a router.)
    parts += [v for k, v in (device.get("extra") or {}).items() if isinstance(v, str) and not k.startswith("ha_")]
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


# ---- score-based category --------------------------------------------------
# Each clue gives points to one or more categories, with a weight that depends on how
# reliable it is; the category with the most points wins (on a tie, TYPE_ORDER order),
# below MIN_TYPE_SCORE the device stays "generic". No rule for a brand:
# what counts are network roles, declared protocols, verified services, ports and words.
W_ROLE, W_DECLARED, W_SERVICE, W_PORT_GUESS, W_WORD, W_BRAND = 10, 8, 4, 1, 2, 3
MIN_TYPE_SCORE = 2
W_PLATFORM_MAX = 3
_PLATFORM_KINDS = {"microcontroller", "bluetooth"}   # types that only tell the hardware platform

# Declared mDNS services (DNS-SD) -> (category, weight)
_MDNS_TYPE = {
    "_googlecast._tcp": ("media", W_DECLARED), "_androidtvremote2._tcp": ("media", W_DECLARED),
    "_amzn-wplay._tcp": ("media", W_DECLARED),
    "_ipp._tcp": ("printer", W_DECLARED), "_ipps._tcp": ("printer", W_DECLARED),
    "_printer._tcp": ("printer", W_DECLARED), "_pdl-datastream._tcp": ("printer", W_DECLARED),
    "_sonos._tcp": ("audio", W_DECLARED), "_raop._tcp": ("audio", 2), "_spotify-connect._tcp": ("audio", 1),
    "_esphomelib._tcp": ("iot", 6), "_workstation._tcp": ("pc", 4), "_rdp._tcp": ("pc", 4),
    "_smb._tcp": ("server", 2), "_mqtt._tcp": ("server", 3), "_home-assistant._tcp": ("server", 6),
}
# Declared UPnP types -> (category, weight)
_UPNP_TYPE = {
    "MediaRenderer": ("media", W_DECLARED), "dial": ("media", W_DECLARED),
    "InternetGatewayDevice": ("router", W_DECLARED), "WFADevice": ("router", W_DECLARED),
    "WLANAccessPointDevice": ("router", W_DECLARED), "MediaServer": ("server", 2), "Printer": ("printer", W_DECLARED),
}
# Local interface that answered -> (category, weight)
# Tasmota and ESPHome are generic firmware (light, plug, sensor, thermostat...): few points,
# so the name or the service of the device decides.
_API_TYPE = {"shelly": ("iot", W_DECLARED), "tasmota": ("iot", 2), "esphome": ("iot", 3),
             "cast": ("media", W_DECLARED), "roku": ("media", W_DECLARED), "sonos": ("audio", W_DECLARED)}
# Typical ports -> category (verified by nmap: W_SERVICE; number only: W_PORT_GUESS)
_PORT_TYPE = {
    554: "media", 1935: "media", 8008: "media", 8009: "media", 7000: "media", 8060: "media",
    631: "printer", 9100: "printer", 515: "printer",
    3389: "pc", 5900: "pc",
    22: "server", 8006: "server", 8123: "server", 2049: "server", 3306: "server", 5432: "server",
    6379: "server", 27017: "server", 1433: "server", 9000: "server",
    1883: "iot", 8883: "iot", 5683: "iot", 6053: "iot",
    1400: "audio",
}
# Ports shared by several categories (SMB: PC, NAS and routers with USB; FTP; DNS): little weight to all.
_PORT_SHARED = {139: ("pc", "server"), 445: ("pc", "server"), 21: ("server",), 53: ("server", "router")}


# ---- home device types (data/device_kinds.json): group + icon + generic words
_kinds_cache: list | None = None


def _kinds() -> list[dict]:
    """Types loaded from the file. Short words (one word, up to 7 letters) count only
    as a whole word, with the plural: "light" does not match inside "lighttpd"."""
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


# Families of clues: the same fact told by several signals (Cast = mDNS service + interface + ports 8008/8009 +
# DIAL) counts ONCE, with the highest score of the family. The words in the text (rules and types) are a single
# family per category. Ports, in total, do not exceed W_PORTS_MAX per category.
_FAMILY_SERVICE = {"_googlecast._tcp": "cast", "_androidtvremote2._tcp": "androidtv"}
_FAMILY_UPNP = {"dial": "cast"}
_FAMILY_PORT = {8008: "cast", 8009: "cast"}
W_PORTS_MAX = 6
MARGIN_BELOW = 5   # below this score, two tied categories are not tie-broken: "generic"


def type_evidence(device: dict, adapter: str | None = None, kinds_out: dict | None = None) -> list[dict]:
    """All the category clues: [{"group", "family", "pts", "source"}]. From here type_scores derives the points
    (once per family) and debug mode shows what decided."""
    from . import roles, signatures  # late imports: roles imports network modules
    ev: list[dict] = []

    def add(group: str, pts: int, family: str, source: str) -> None:
        ev.append({"group": _MERGED_GROUPS.get(group, group), "family": family, "pts": pts, "source": source})

    ip = device.get("ip")
    upnp_types = roles.upnp_types(ip)
    # IoT platforms (Shelly, Tasmota, ESPHome, Espressif chips...): they say "it is a smart device", not what it does.
    # They are worth little and in total (W_PLATFORM_MAX): a word that states the function always wins.
    platform = 0
    if adapter and adapter.startswith("shelly"):
        platform += W_ROLE  # answer from its direct API
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
            # the Cast port is in the Cast family (counts once with service and API); the others are "port" families
            add(kind, W_SERVICE if p.get("confirmed") else W_PORT_GUESS, fam or "port:%s" % port, "porta %s" % port)
        for shared in _PORT_SHARED.get(port, ()):
            add(shared, W_PORT_GUESS, "port:%s:%s" % (port, shared), "porta %s" % port)
    text, tokens, ports = _blob(device)
    for kind, rule in _RULES.items():
        if any(s in text for s in rule["subs"]) or tokens & rule["toks"]:
            add(kind, W_WORD, "words", "parola nel testo")
    # Product brand (or MAC manufacturer if it only sells devices of that type); the name counts too (a PC
    # called "MSI"): the MAC manufacturer is often just the network card, the name is chosen by whoever installs the system.
    brand_tokens = set(_TOKEN_RE.findall(" ".join(filter(None, [
        device.get("brand"), device.get("name"),
        device.get("vendor") if device.get("vendor_role") == "brand" else None])).lower()))
    # Home Assistant integrations attached to the device: they declare what it is (onvif, braviatv...).
    ha_card = device.get("ha_registry") or {}
    for dom in (ha_card.get("domains") or []):
        entry = _ha_integrations().get(dom)
        # A router integration (UniFi, FRITZ!Box, MikroTik...) also lists every client it sees, as a device with only a
        # device_tracker: that one is not the router. The router itself has other entities (sensors, switches, buttons...).
        if entry and entry.get("group") == "router" and not entry.get("platform") and ha_card.get("entity_domains") is not None                 and not (set(ha_card["entity_domains"]) - {"device_tracker"}):
            continue
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
    # Product signatures (app/data/signatures.json): where the generic signals are ambiguous the declared model decides.
    for sig in signatures.matches({**device, "extra": extra}, upnp_types):
        add(sig["group"], int(sig.get("weight", W_ROLE)), "sig:" + sig["id"], "firma " + sig["id"])
        if sig.get("kind") and kinds_out is not None:
            kinds_out[sig["kind"]] = kinds_out.get(sig["kind"], 0) + int(sig.get("weight", W_ROLE))
    if platform:
        add("iot", min(platform, W_PLATFORM_MAX), "platform", "piattaforma IoT")
    # Only IoT ports (MQTT, CoAP) and nothing else: an embedded device.
    if ports and ports <= {1883, 8883, 5683}:
        add("iot", 3, "port:iot", "solo porte IoT")
    return ev


def _aggregate(ev: list[dict]) -> dict[str, int]:
    """Points per category: for each family the highest value, families are summed; ports have a cap."""
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
    """Points per category (see above), for understanding and for tests. kinds_out (optional)
    is filled with the points for each device type, from which the icon is chosen."""
    return _aggregate(type_evidence(device, adapter, kinds_out))


def icon_for(device: dict, adapter: str | None = None, kind: str | None = None) -> str | None:
    """Name of the MDI icon best suited to the device: the one of the type (data/device_kinds.json)
    with the most points within the chosen category; None = the category icon."""
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
    """True for the types that are a specific product (Home Assistant, Raspberry Pi): the name
    is the type itself, without a brand in front."""
    return any(kd["id"] == kind_id and kd.get("product") for kd in _kinds())


def best_kind(device: dict, adapter: str | None = None) -> str | None:
    """Id of the device type (data/device_kinds.json) with the most points, in the chosen category."""
    group = infer_type(device, adapter)
    kinds_out: dict[str, int] = {}
    type_scores(device, adapter, kinds_out)
    best, best_pts = None, 0
    for kd in _kinds():
        if kd["group"] == group and kinds_out.get(kd["id"], 0) > best_pts:
            best, best_pts = kd["id"], kinds_out[kd["id"]]
    return best


def infer_type(device: dict, adapter: str | None = None) -> str:
    """Device category by score (type_scores). The is_mobile flag (user choice
    or the probe "mobile" score) wins over everything."""
    if device.get("is_mobile"):
        return "phone"
    scores = type_scores(device, adapter)
    if not scores:
        return "generic"
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], TYPE_ORDER.index(kv[0]) if kv[0] in TYPE_ORDER else 99))
    best = ranked[0]
    if best[1] < MIN_TYPE_SCORE:
        return "generic"
    # Two tied categories with weak clues: no random pick (like Nmap when the two best are close).
    if len(ranked) > 1 and best[1] < MARGIN_BELOW and ranked[1][1] >= MIN_TYPE_SCORE and best[1] - ranked[1][1] < 1:
        return "generic"
    return best[0]


def effective_type(device: dict, cfg: dict | None = None) -> str:
    """Category chosen by hand (cfg["type_user"]) or the scored one."""
    cfg = cfg or {}
    chosen = cfg.get("type_user")
    if chosen in TYPE_ORDER or chosen == "generic":
        return chosen
    return infer_type(device, cfg.get("adapter"))


# ---- configuration (adapter, "mobile" choice) with file cache ----
_cfg_cache: dict = {"mtime": None, "map": {}}


def config_map() -> dict[str, dict]:
    """{id: configuration} from devices.yaml, re-read only if the file changes
    (needed to know the adapter and manual choice of each device without
    reading the disk on every event)."""
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
    """Device from the shared state -> compact format for the /ha UI.
    Texts and field names in the current language (i18n.use)."""
    cfg = cfg or {}
    logo = brand_logo.logo_for(device.get("brand"))
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
        # Two levels: vendor = MAC manufacturer (chip/board), brand = product
        # brand (None if unknown); brand_source/confidence say where it comes from.
        "vendor": device.get("vendor"),
        "vendor_role": device.get("vendor_role"),
        "brand": device.get("brand"),
        "brand_source": device.get("brand_source"),
        "brand_confidence": device.get("brand_confidence"),
        "brand_evidence": device.get("brand_evidence"),
        "brand_declared": device.get("brand_declared"),
        # Logo of the brand shown now (None if it has none): worked out here every time, never stored.
        "logo": logo and logo["id"],
        "logo_color": logo and logo["color"],
        # battery: "yes" | "no" | None (unknown), with the source; a battery-powered
        # network device (sensor) is not "mobile".
        "battery": device.get("battery"),
        "battery_source": device.get("battery_source"),
        "type": _t,
        "icon": icon_for(device, cfg.get("adapter"), _t),
        "is_mobile": bool(device.get("is_mobile")),
        # "auto" = the name/scans decide; "yes"/"no" = choice made by hand.
        "mobile_mode": "auto" if mobile_cfg is None else ("yes" if mobile_cfg else "no"),
        "name_source": cfg.get("name_source"),
        "wol_ok": bool(cfg.get("wol_ok")),
        "ha_share": bool(cfg.get("ha_share")),
        "type_user": cfg.get("type_user"),
        "brand_user": cfg.get("brand_user"),
        "focus": bool(cfg.get("focus")),
        "focus_note": cfg.get("focus_note"),
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
        "web_open": device.get("web_open"),
        "deep_empty_at": device.get("deep_empty_at"),
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
    """Counts, brands, types and search status. Takes the devices
    from the shared state (not compact): it is pure, with no disk access."""
    online = sum(1 for d in devices if d.get("online"))
    mobile = [d for d in devices if d.get("is_mobile")]
    brands: dict[str | None, int] = {}
    chips: dict[str, int] = {}  # MAC manufacturer of devices with no known brand
    types: dict[str, int] = {}
    cfg = config_map()
    for d in devices:
        brand = d.get("brand") or None  # the PRODUCT brand, never the board manufacturer
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
        # Average response time of the online devices that measured it.
        "latency_avg_ms": _avg_latency(devices),
        "poll": {
            "interval_ms": poll.get("interval_ms"), "next_in_ms": poll.get("next_in_ms"),
            "paused": bool(poll.get("paused")), "paused_in_ms": poll.get("paused_in_ms"),
            "paused_total_ms": poll.get("paused_total_ms"),
        },
        "activity": {"search": bool(activity.get("search")), "rescanning": list(activity.get("rescanning") or [])},
        "new_devices": {"count": new_devices.get("count", 0), "devices": new_devices.get("devices", [])},
    }


# ---- event log (logbook) ----
def recent_presence(limit: int, hist: History = history) -> list[dict]:
    """Latest online/offline events from the history, most recent first.
    Reads presence_events without touching history.py (same connection and the
    same lock as the other methods)."""
    limit = max(1, min(int(limit), 200))
    with hist._lock:
        rows = hist._db.execute(
            "SELECT id, device_id, ip, online, ts FROM presence_events ORDER BY ts DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [{"id": r["id"], "device_id": r["device_id"], "ip": r["ip"], "online": bool(r["online"]), "ts": r["ts"]}
            for r in rows]


def logbook_entries(rows: list[dict], devices: dict[str, dict], cfg: dict[str, dict] | None = None) -> list[dict]:
    """Raw events + name and type of the device (if it is no longer in the
    configuration the last known IP remains) + sentence in the current language."""
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
    """Window of history.presence_segments with times as whole seconds:
    fewer bytes in the responses that cover all devices."""
    return {
        "from": int(window["from"]), "to": int(window["to"]),
        "segments": [{"from": int(s["from"]), "to": int(s["to"]), "online": s["online"]} for s in window["segments"]],
        "online_pct": window["online_pct"],
    }
