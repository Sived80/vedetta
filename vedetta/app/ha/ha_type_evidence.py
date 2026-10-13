"""ha_type_evidence: moved out of ha_data.py (see tools/split_module.py)."""
from functools import lru_cache
from typing import NamedTuple
from .. import datafile
from ..recognition import roles, signatures
from .ha_registry import observed_only, tracker_only
from .ha_type_text import TYPE_ORDER, W_BRAND, W_DECLARED, W_PORT_GUESS, W_ROLE, W_SERVICE, W_WORD, _MERGED_GROUPS, _MODEL_WORDS, _PC_PORTS, _PORT_RE, _TOKEN_RE, _blob, _blob_extra_texts, _blob_name_parts, _blob_port_labels, _model_text, _word_pts, rules  # noqa: F401


MIN_TYPE_SCORE = 2


W_PLATFORM_MAX = 3


_PLATFORM_KINDS = {"microcontroller", "bluetooth"}   # types that only tell the hardware platform


# Declared mDNS services (DNS-SD) -> (category, weight). A service that any general responder publishes weighs 1 (_workstation._tcp: avahi-daemon publishes it only when publish-workstation is on, the
# default depends on the version, and recent macOS does too: an embedded Linux box has it as a PC does); a service that says what the device is weighs W_DECLARED or its own value.
_MDNS_TYPE = {
    "_googlecast._tcp": ("media", W_DECLARED), "_androidtvremote2._tcp": ("media", W_DECLARED),
    "_amzn-wplay._tcp": ("media", W_DECLARED),
    "_ipp._tcp": ("printer", W_DECLARED), "_ipps._tcp": ("printer", W_DECLARED),
    "_printer._tcp": ("printer", W_DECLARED), "_pdl-datastream._tcp": ("printer", W_DECLARED),
    "_sonos._tcp": ("audio", W_DECLARED), "_raop._tcp": ("audio", 2), "_spotify-connect._tcp": ("audio", 1),
    "_esphomelib._tcp": ("iot", 6), "_workstation._tcp": ("pc", 1), "_rdp._tcp": ("pc", 4),
    "_smb._tcp": ("server", 2), "_mqtt._tcp": ("server", 3), "_home-assistant._tcp": ("server", 6),
}


# Declared UPnP types -> (category, weight)
_UPNP_TYPE = {
    "MediaRenderer": ("media", W_DECLARED), "dial": ("media", W_DECLARED),
    "InternetGatewayDevice": ("router", W_DECLARED), "WFADevice": ("router", W_DECLARED),
    "WLANAccessPointDevice": ("router", W_DECLARED), "MediaServer": ("server", 2), "Printer": ("printer", W_DECLARED),
}


# Local interface that answered -> (category, weight), from data/local_api.json.
# Tasmota and ESPHome are generic firmware (light, plug, sensor, thermostat...): few points,
# so the name or the service of the device decides.
@lru_cache(maxsize=1)
def _api_types() -> dict:
    rows = datafile.read(datafile.DATA_DIR / "local_api.json", "api_types", what="Table of local interfaces", default={})
    return {api: (row["group"], W_DECLARED if row["weight"] == "declared" else int(row["weight"])) for api, row in rows.items()}


@lru_cache(maxsize=1)
def _platform_adapters() -> tuple:
    """The beginnings of the names of the adapters whose answer comes from the direct API of an IoT platform."""
    return tuple(datafile.read(datafile.DATA_DIR / "local_api.json", "platform_adapters", what="Table of local interfaces", default=[]))


# Typical ports -> category (verified by nmap: W_SERVICE; number only: W_PORT_GUESS)
_PORT_TYPE = {
    554: "media", 1935: "media", 8008: "media", 8009: "media", 7000: "media", 8060: "media",
    631: "printer", 9100: "printer", 515: "printer",
    3389: "pc", 5900: "pc",
    22: "server", 8006: "server", 8123: "server", 2049: "server", 3306: "server", 5432: "server",
    6379: "server", 27017: "server", 1433: "server", 9000: "server",
    1883: "iot", 8883: "iot", 5683: "iot", 6053: "iot",
    502: "iot",   # Modbus TCP (inverters, meters, wall boxes): open port only, nothing is ever sent to it; weak, shared with controllers
    1400: "audio",
}


# Ports shared by several categories (SMB: PC, NAS and routers with USB; FTP; DNS): little weight to all.
_PORT_SHARED = {139: ("pc", "server"), 445: ("pc", "server"), 21: ("server",), 53: ("server", "router")}


# ---- home device types (data/device_kinds.json): group + icon + generic words
_kinds_cache: list | None = None


_ha_table_cache: dict | None = None


def _ha_integrations() -> dict:
    global _ha_table_cache
    if _ha_table_cache is None:
        _ha_table_cache = datafile.read(datafile.DATA_DIR / "ha_integrations.json", "integrations", what="Table of Home Assistant integrations", default={})
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
    return _Clues(device, adapter, kinds_out).collect()


class _Words(NamedTuple):
    """What the matching of the device types reads: the text of the device, its words, its declared model, the words of its brand, its declared mDNS services and UPnP types."""
    text: str
    tokens: set
    model: tuple
    brand_tokens: set
    services: set
    upnp: set


class _Clues:
    """The clues of one device, found one kind of signal at a time; every stage reports what it finds through `add`. `platform` collects the points that only say
    "IoT platform" (Shelly, Tasmota, ESPHome, Espressif chips...): they say "it is a smart device", not what it does, so they are worth little and are counted once, with a cap (W_PLATFORM_MAX):
    a word that states the function always wins."""

    def __init__(self, device: dict, adapter: str | None, kinds_out: dict | None):
        self.device, self.kinds_out = device, kinds_out
        self.extra = device.get("extra") or {}
        self.ev: list[dict] = []
        self.platform = W_ROLE if adapter and adapter.startswith(_platform_adapters()) else 0   # answer from its direct API

    def add(self, group: str, pts: int, family: str, source: str) -> None:
        self.ev.append({"group": _MERGED_GROUPS.get(group, group), "family": family, "pts": pts, "source": source})

    def collect(self) -> list[dict]:
        upnp_types = roles.upnp_types(self.device.get("ip"))
        services = _declared_services(self.extra)
        self.signals(upnp_types, services)
        self.ports()
        text, tokens, port_numbers = _blob(self.device)
        words = _Words(text, tokens, _model_text(self.device), _brand_tokens(self.device), set(services), set(upnp_types))
        self.words(words)
        self.homeassistant()
        self.kinds(_without_dual_maker(words, self.device))
        return self.finish(upnp_types, port_numbers)

    def signals(self, upnp_types: list, services: list) -> None:
        """Network roles, declared mDNS services and UPnP types, the interface that answered, ONVIF and RTSP."""
        if _has_network_role(roles, self.device.get("ip")):
            self.add("router", W_ROLE, "role", "ruolo di rete")
        self.table_hits(services, _MDNS_TYPE, _FAMILY_SERVICE, "svc:", "mDNS ")
        self.table_hits(upnp_types, _UPNP_TYPE, _FAMILY_UPNP, "upnp:", "UPnP ")
        self.api()
        if _declares_onvif(self.extra):
            self.add("media", W_DECLARED, "onvif", "ONVIF")
        if self.extra.get("rtsp_server"):
            self.add("media", 6, "rtsp", "RTSP")

    def table_hits(self, items, table: dict, families: dict, prefix: str, label: str) -> None:
        """Reports every item found in the table of declared types, in order."""
        for item in items:
            if item in table:
                group, pts = table[item]
                self.add(group, pts, families.get(item, prefix + item), label + item)

    def api(self) -> None:
        """The local interface that answered: an IoT platform gives points to the platform, the others are reported as a clue of their type."""
        api = self.extra.get("api_source")
        if api not in _api_types():
            return
        kind_api, pts_api = _api_types()[api]
        if kind_api == "iot":
            self.platform += pts_api
            return
        self.add(kind_api, pts_api, "cast" if api == "cast" else "api:" + api, "API " + api)

    def ports(self) -> None:
        for p in self.device.get("scanned_ports") or []:
            m = _PORT_RE.match(p.get("label") or "")
            port = int(m.group(1)) if m else None
            kind = _PORT_TYPE.get(port)
            if kind:
                fam = _FAMILY_PORT.get(port)
                # the Cast port is in the Cast family (counts once with service and API); the others are "port" families
                self.add(kind, W_SERVICE if p.get("confirmed") else W_PORT_GUESS, fam or "port:%s" % port, "porta %s" % port)
            for shared in _PORT_SHARED.get(port, ()):
                self.add(shared, W_PORT_GUESS, "port:%s:%s" % (port, shared), "porta %s" % port)

    def words(self, w: _Words) -> None:
        for group, model_words in _MODEL_WORDS.items():
            if w.model[1] & model_words:
                self.add(group, W_DECLARED, "model", "modello dichiarato")
        for kind, rule in rules().items():
            if any(s in w.text for s in rule["subs"]) or w.tokens & rule["toks"]:
                self.add(kind, _word_pts(W_WORD, rule["subs"], rule["toks"], w.model), "words", "parola nel testo")

    def homeassistant(self) -> None:
        """Home Assistant integrations attached to the device: they declare what it is (onvif, braviatv...)."""
        ha_card = self.device.get("ha_registry") or {}
        for dom in (ha_card.get("domains") or []):
            entry = _ha_integrations().get(dom)
            if not entry or tracker_only(ha_card) or _observed_client(entry, ha_card):
                continue
            self.integration(entry, dom)
        self.unlisted_entities(ha_card)

    def integration(self, entry: dict, dom: str) -> None:
        """What a known integration says about the device: an IoT platform gives points to the platform, else its group is reported; its type is counted in kinds_out."""
        if entry.get("platform"):
            self.platform += W_PLATFORM_MAX
        else:
            self.add(entry["group"], W_DECLARED, "ha", "integrazione HA " + dom)
        if entry.get("kind") and self.kinds_out is not None:
            self.kinds_out[entry["kind"]] = self.kinds_out.get(entry["kind"], 0) + W_DECLARED

    def unlisted_entities(self, ha_card: dict) -> None:
        """The integration is not in the table (Daikin, Broadlink, Sonoff...): what Home Assistant does with the device still says something. A player or a camera is
        media; switches, lights, climate, covers... say "smart device" (little, like any platform)."""
        real_kinds = set(ha_card.get("entity_domains") or []) - {"device_tracker"}
        if not real_kinds or any(_ha_integrations().get(d) for d in (ha_card.get("domains") or [])):
            return
        media = real_kinds & {"media_player", "camera"}
        if media:
            self.add("media", W_SERVICE, "ha_entities", "entita HA " + ",".join(sorted(media)))
            return
        self.platform += 2

    def kinds(self, w: _Words) -> None:
        """The clues of the device types (data/device_kinds.json): words, declared services, brand."""
        for kd in _candidate_kinds(w):
            pts = self.kind_pts(kd, w)
            if not pts:
                continue
            if kd["id"] in _PLATFORM_KINDS:
                self.platform += pts
            elif self.kinds_out is not None:
                self.kinds_out[kd["id"]] = self.kinds_out.get(kd["id"], 0) + pts      # added up with what the integration and the signatures gave (it was assigned: their points were lost)

    def kind_pts(self, kd: dict, w: _Words) -> int:
        """All the points that the clues give to one type, in the order words, mDNS, UPnP, brand."""
        pts = self.kind_word_pts(kd, w)
        pts += self.kind_declared_pts(kd, w.services & kd["mdns"], _FAMILY_SERVICE, "svc:", "mDNS ")
        pts += self.kind_declared_pts(kd, w.upnp & kd["upnp"], _FAMILY_UPNP, "upnp:", "UPnP ")
        if w.brand_tokens & kd["brands"]:
            pts += W_BRAND
            self.add(kd["group"], W_BRAND, "brand", "marca: " + kd["id"])
        return pts

    def kind_word_pts(self, kd: dict, w: _Words) -> int:
        """Points of the words of a type found in the text (0 if none); reported unless the type only tells the platform."""
        if not (any(s in w.text for s in kd["subs"]) or w.tokens & kd["toks"]):
            return 0
        word_pts = _word_pts(kd["w"], kd["subs"], kd["toks"], w.model)
        if kd["id"] not in _PLATFORM_KINDS:
            self.add(kd["group"], word_pts, "words", "parola: " + kd["id"])
        return word_pts

    def kind_declared_pts(self, kd: dict, found: set, families: dict, prefix: str, label: str) -> int:
        """W_DECLARED for each declared protocol of the type (in sorted order); reported unless the type only tells the platform."""
        for item in sorted(found):
            if kd["id"] not in _PLATFORM_KINDS:
                self.add(kd["group"], W_DECLARED, families.get(item, prefix + item), label + item)
        return W_DECLARED * len(found)

    def finish(self, upnp_types: list, port_numbers: set) -> list[dict]:
        # Product signatures (app/data/signatures.json): where the generic signals are ambiguous the declared model decides.
        for sig in signatures.matches({**self.device, "extra": self.extra}, upnp_types):
            self.add(sig["group"], int(sig.get("weight", W_ROLE)), "sig:" + sig["id"], "firma " + sig["id"])
            if sig.get("kind") and self.kinds_out is not None:
                self.kinds_out[sig["kind"]] = self.kinds_out.get(sig["kind"], 0) + int(sig.get("weight", W_ROLE))
        if self.platform:
            self.add("iot", min(self.platform, W_PLATFORM_MAX), "platform", "piattaforma IoT")
        # Only IoT ports (MQTT, CoAP) and nothing else: an embedded device.
        if port_numbers and port_numbers <= {1883, 8883, 5683}:
            self.add("iot", 3, "port:iot", "solo porte IoT")
        return self.ev


def _without_dual_maker(w: _Words, device: dict) -> _Words:
    """The words of the device types are the words of a function ("curtain", "speaker"), not of a maker. The manufacturer of the MAC prefix with the role "dual" (data/brands.json: it makes network
    cards AND finished products) says who made the card, not what the device does: its name is not looked for among those words, in the vendor field or in the name of the device (one sense for
    all the device: "Tenda" is the maker, never a curtain). What the maker tells goes through the tables of makers (type_words.json, the brands of the types)."""
    if device.get("vendor_role") != "dual":
        return w
    maker = set(_TOKEN_RE.findall(str(device.get("vendor") or "").lower()))
    if not maker:
        return w
    return w._replace(text=_TOKEN_RE.sub(lambda m: " " if m.group(0) in maker else m.group(0), w.text), tokens=w.tokens - maker)


def _observed_client(entry: dict, ha_card: dict) -> bool:
    """An integration that OBSERVES the network (data/ha_integrations.json, "observer") declares the device only when it owns it (see ha_registry.observed_only): its clients have entities
    too (tracker, bandwidth sensors, block switches), which say they are on the network, not what they are."""
    return bool(entry.get("observer")) and observed_only(ha_card, {d for d, e in _ha_integrations().items() if e.get("observer")})


def _brand_tokens(device: dict) -> set:
    """The words of the product brand (or MAC manufacturer if it only sells devices of that type); the name counts too (a PC called "MSI"): the MAC manufacturer is often just the network card,
    the name is chosen by whoever installs the system."""
    return set(_TOKEN_RE.findall(" ".join(filter(None, [
        device.get("brand"), device.get("name"),
        device.get("vendor") if device.get("vendor_role") == "brand" else None])).lower()))


def _has_network_role(roles_, ip) -> bool:
    return bool({"gateway", "router", "ap", "repeater"} & set(roles_.roles_for(ip)))


def _declared_services(extra: dict) -> list[str]:
    """The mDNS services of the device from its extra data, without spaces and empty items."""
    return [s for s in (extra.get("mdns_services") or "").replace(" ", "").split(",") if s]


def _declares_onvif(extra: dict) -> bool:
    return any(extra.get(k) for k in ("onvif_name", "onvif_hardware", "onvif_manufacturer")) or "NetworkVideoTransmitter" in (extra.get("wsd_types") or "")


class _KindIndex(NamedTuple):
    """For each thing that can give points to a type, the positions (in the file) of the types that have it."""
    subs: dict
    tokens: dict
    mdns: dict
    upnp: dict
    brands: dict


_index_of: list = [None, None]      # [the list of types the index was made from, the index]


def _kind_index(kinds: list[dict]) -> _KindIndex:
    if _index_of[0] is not kinds:
        _index_of[:] = [kinds, _build_index(kinds)]
    return _index_of[1]


def _build_index(kinds: list[dict]) -> _KindIndex:
    """For each word, token, service, UPnP type and brand: the positions of the kinds that list it."""
    index = _KindIndex({}, {}, {}, {}, {})
    for position, kd in enumerate(kinds):
        for table, keys in ((index.subs, kd["subs"]), (index.tokens, kd["toks"]), (index.mdns, kd["mdns"]), (index.upnp, kd["upnp"]), (index.brands, kd["brands"])):
            for key in keys:
                table.setdefault(key, []).append(position)
    return index


def _candidate_kinds(w: _Words) -> list[dict]:
    """The types that can give points to this device, in the order of the file: the ones with a word of theirs in the text or among the words, a declared mDNS service or UPnP type, or the brand.
    Every other type gives 0 points and reports nothing."""
    kinds = _kinds()
    index = _kind_index(kinds)
    hit: set[int] = set()
    for sub, positions in index.subs.items():
        if sub in w.text:
            hit.update(positions)
    for table, mine in ((index.tokens, w.tokens), (index.mdns, w.services), (index.upnp, w.upnp), (index.brands, w.brand_tokens)):
        for key in mine & table.keys():
            hit.update(table[key])
    return [kinds[position] for position in sorted(hit)]


def _kinds() -> list[dict]:
    """Types loaded from the file. Short words (one word, up to 7 letters) count only
    as a whole word, with the plural: "light" does not match inside "lighttpd"."""
    global _kinds_cache
    if _kinds_cache is None:
        _kinds_cache = [_build_kind(k) for k in _read_kind_rows()]
    return _kinds_cache


def _read_kind_rows() -> list:
    """The raw entries of data/device_kinds.json ([] when the file is missing or broken: told once in the log)."""
    return datafile.read(datafile.DATA_DIR / "device_kinds.json", "kinds", what="Table of device kinds", default=[])


def _build_kind(k: dict) -> dict:
    """One entry of the file -> the type used by the matching code."""
    toks = set(k.get("tokens") or [])
    subs = _split_words(k.get("words"), toks)
    toks |= {t + "s" for t in list(toks)}
    return {"id": k["id"], "group": _MERGED_GROUPS.get(k["group"], k["group"]), "icon": k["icon"], "subs": subs, "toks": toks,
            "w": int(k.get("w", 2)), "mdns": set(k.get("mdns") or []), "upnp": set(k.get("upnp") or []),
            "brands": set(k.get("brands") or []), "product": bool(k.get("product"))}


def _split_words(words, toks: set) -> list[str]:
    """Substrings for the long or composite words; the short single words are added to `toks` (whole-word matches only)."""
    subs = []
    for w in words or []:
        w = w.lower()
        if " " not in w and "-" not in w and len(w) <= 7:
            toks.add(w)
        else:
            subs.append(w)
    return subs


def type_scores(device: dict, adapter: str | None = None, kinds_out: dict | None = None) -> dict[str, int]:
    """Points per category (see above), for understanding and for tests. kinds_out (optional)
    is filled with the points for each device type, from which the icon is chosen."""
    return _aggregate(type_evidence(device, adapter, kinds_out))


def family_best(ev: list[dict]) -> dict[tuple, int]:
    """For each (category, family) the clue that counts: the strongest, in favour (positive points) or against (negative; on a tie, in favour); the others of the same family are repetitions of the same fact. Shared by the
    sum of the points and by the mark "counted" of the evidence shown."""
    best: dict[tuple, int] = {}
    for e in ev:
        key = (e["group"], e["family"])
        current = best.get(key, 0)
        best[key] = e["pts"] if (abs(e["pts"]), e["pts"]) > (abs(current), current) else current      # equal strength: the one in favour (the result never depends on the order)
    return best


def _aggregate(ev: list[dict]) -> dict[str, int]:
    """Points per category: for each family the strongest clue (in favour adds, against takes away), families are summed; ports have a cap."""
    best = family_best(ev)
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
