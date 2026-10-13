"""Identity of a device in a single place: product brand, "mobile" and
battery. Used by probe.py. Common principle (the same as Fing, Fingerbank and the
Home Assistant integrations): no verdict from a single clue, but multiple
pieces of evidence, each with a source and a confidence, and the device's own
direct sources beat the indirect ones.

BRAND. The MAC prefix (OUI) is the manufacturer of the BOARD, not of the product: see
brands.py (vendor_roles: component, virtual, dual, brand). Here the
result is exposed at two levels:
  vendor            manufacturer of the MAC prefix (chip/board), cleaned up
  vendor_role       component | virtual | dual | brand | private (random MAC) | None
  brand             product brand, None if unknown (never the chip!)
  brand_source      dhcp | name | web | declared | oui | None
  brand_confidence  high | medium | low | None
  brand_evidence    confirmed | plausible | None (undetermined). Confirmed only
                    when the device DECLARED it (UPnP/mDNS/ONVIF), when the real
                    MAC prefix belongs to a brand; every inference (name, web, DHCP)
                    stays plausible.
  brand_declared    value declared by the device that is not a known brand
                    (e.g. "IPCAM" of a white-label camera): "no brand
                    declared", not to be confused with "undetermined".
The network gateway (dual + gateway = router of its brand) is the only
"network" confirmation for ambiguous manufacturers like TP-Link.

MOBILE. "Mobile" = phone, tablet, laptop: an object that follows a person.
Additive score, threshold MOBILE_THRESHOLD (3); the user's manual choice
(devices.yaml "mobile") always wins, decided by probe.py:
  +3 phone-like name / iOS DHCP fingerprint / iphone-ipad hostname  (dhcp.mobile_score)
  +2 Android DHCP fingerprint (needs a second clue), +1 private MAC (+1 without ports)
  -2 Windows/macOS/Linux fingerprint (dhcp.mobile_score)
  +3 mobile model (iPhone15,2, iPad, SM-xxxx), +2 laptop (MacBook), -3 fixed (Mac mini, HomePod)
  +1/+2 presence: 6/14 or more online/offline transitions in 7 days (phones
      come and go on the network, fixed equipment does not); not enough on its own
  -4 network battery (Shelly sensor, UPS): battery-powered but FIXED, not mobile.
  -4 receives or plays video (mDNS Chromecast/Android TV/Whisperplay, UPnP MediaRenderer or
      DIAL, "TV" service or system recognized by nmap): TV, stick, box.
  +2 "Android" in the name: it is the system, not the type (needs a second clue).
  +3 mDNS service that only phones announce (Android Nearby, iOS sync).
  +1 no listening ports, but only if there is already another clue.

BATTERY. Attribute battery = yes | no | None (unknown) with battery_source:
  api     device response: Shelly Gen1 /status field "bat", Gen2
          Shelly.GetStatus component "devicepower:0"
  scan    the same data saved by the last scan
  hint    text (model, SNMP, web title) recognized by "battery_hints" (UPS, sensors)
  model   phone/laptop from the model (battery, but also mobile) or fixed appliance (no)
"""
import time

from . import brands
from .. import procfs
from ..scan import dhcp
from .vendor_lookup import is_private_mac, lookup_vendor
from .brands import normalize_brand

MOBILE_THRESHOLD = 3
# What each clue adds to (or takes from) the mobile score; the DHCP clues have their own table in scan/dhcp.py.
MOBILE_WEIGHTS = {"name_weak": 2, "model_mobile": 3, "model_laptop": 2, "model_fixed": -3, "churn_strong": 2, "churn_weak": 1,
                  "mac_rotation": 3, "mobile_service": 3, "no_ports": 1, "plays_video": -4, "fixed_battery": -4}
_W = MOBILE_WEIGHTS
CHURN_WINDOW_DAYS = 7
CHURN_REFRESH_S = 600
_CHURN_WEAK, _CHURN_STRONG = 6, 14

_NO_GATEWAY = object()
_gateway_cache: dict = {"value": _NO_GATEWAY}


def default_gateway(route_path: str = "/proc/net/route") -> str | None:
    """IP of the default gateway (from /proc/net/route, Linux); None if it cannot be read.
    Computed only once: a home LAN's gateway does not change."""
    is_system_path = route_path == "/proc/net/route"
    if _gateway_cache["value"] is not _NO_GATEWAY and is_system_path:
        return _gateway_cache["value"]
    gateway = _read_gateway(route_path)
    if is_system_path and gateway:
        _gateway_cache["value"] = gateway
    return gateway


def _read_gateway(route_path: str) -> str | None:
    """The gateway of the first default route of the file; None if there is none or the file cannot be read."""
    try:
        for cols in procfs.table(route_path):
            if _is_default_route(cols):
                return _gateway_text(cols[2])
    except ValueError:         # a bad number (or a byte that is not ASCII) ends the reading with no answer
        pass
    return None


def _is_default_route(cols: list[str]) -> bool:
    """A line of /proc/net/route that is the default route and has the gateway flag (RTF_GATEWAY) set."""
    return len(cols) > 2 and cols[1] == "00000000" and bool(int(cols[3], 16) & 2)


def _gateway_text(hex_address: str) -> str:
    """Dotted address from the little-endian hexadecimal field of /proc/net/route."""
    raw = int(hex_address, 16).to_bytes(4, "little")
    return ".".join(str(b) for b in raw)


def identify_brand(mac: str | None, *, names=(), upnp_manufacturer: str | None = None, declared=(),
                   web_text: str | None = None, os_family: str | None = None, is_gateway: bool = False,
                   raw_vendor: str | None = None) -> dict:
    """Two-level brand (see the module docstring). raw_vendor is the raw
    name from nmap/arp-scan, used only if the prefix database does not know the MAC."""
    vendor = _vendor_of_mac(mac, raw_vendor)
    found = brands.resolve(vendor, names=list(names), upnp_manufacturer=upnp_manufacturer, declared=declared,
                           web_text=web_text, os_family=os_family, is_gateway=is_gateway)
    role = found["role"] or ("private" if is_private_mac(mac) else None)
    declared_brands = {brands.known_brand(v) for v in (upnp_manufacturer, *declared) if v}
    evidence = _brand_evidence(found, role, vendor, mac, declared_brands)
    generic = None
    if not found["brand"]:
        generic = next((str(v).strip() for v in (upnp_manufacturer, *declared) if v and str(v).strip()), None)
    return {"vendor": vendor, "vendor_role": role, "brand": found["brand"],
            "brand_source": found["source"], "brand_confidence": found["confidence"],
            "brand_evidence": evidence, "brand_declared": generic}


def _vendor_of_mac(mac, raw_vendor):
    """The manufacturer of the MAC prefix; if the database does not know it, the cleaned raw name (but not for a random MAC)."""
    vendor = lookup_vendor(mac)
    if vendor is None and raw_vendor and not is_private_mac(mac):
        vendor = normalize_brand(raw_vendor)
    return vendor


def _brand_evidence(found, role, vendor, mac, declared_brands):
    """"confirmed" when the device declares the brand or the MAC prefix agrees; "plausible" for any other inference; None without a brand."""
    if not found["brand"]:
        return None
    source = found["source"]
    # Confirmed also when the chosen source is another one but the device declares the
    # same brand (e.g. name "SONY XR-55X92K" and UPnP manufacturer "Sony").
    if (source == "declared" or found["brand"] in declared_brands
            or _oui_brand_mac(source, role, mac) or _mac_and_name_agree(role, mac, vendor, found["brand"])):  # MAC and name agree
        return "confirmed"
    return "plausible"


def _oui_brand_mac(source, role, mac) -> bool:
    return source == "oui" and role == "brand" and not is_private_mac(mac)


def _mac_and_name_agree(role, mac, vendor, brand) -> bool:
    return role == "brand" and not is_private_mac(mac) and brands.known_brand(vendor) == brand


def battery_assess(*, api: bool | None = None, scan: str | None = None, texts=(),
                   model_class: str | None = None) -> tuple[str | None, str | None]:
    """(battery, source): from the device's direct response, then from the saved
    scan, then from the model, finally from textual clues. (None, None) = unknown."""
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
_macs: dict = {"ts": 0.0, "data": {}}


def presence_churn(device_id: str, now: float | None = None) -> int:
    """Online/offline transitions of the device in the last 7 days. A single
    query for all devices, refreshed every 10 minutes."""
    return _window_count(_churn, "presence_flaps", device_id, now)


def presence_mac_changes(device_id: str, now: float | None = None) -> int:
    """How many different private MACs this card has used in the last 7 days (see History.private_mac_counts)."""
    return _window_count(_macs, "private_mac_counts", device_id, now)


def _window_count(cache: dict, query: str, device_id: str, now: float | None) -> int:
    """The count of a device from a history query over the last CHURN_WINDOW_DAYS days: one query for all the devices, refreshed at most every CHURN_REFRESH_S."""
    now = time.time() if now is None else now
    if now - cache["ts"] > CHURN_REFRESH_S:
        try:
            from ..storage.history import history  # late import: opens the database
            cache["data"] = getattr(history, query)(now - CHURN_WINDOW_DAYS * 86400)
        except Exception:
            pass  # keep the last known value (or none)
        cache["ts"] = now
    return cache["data"].get(device_id, 0)


def mobile_assess(*, mac: str | None, name_is_mobile: bool, has_ports: bool | None,
                  model_class: str | None = None, battery: str | None = None,
                  battery_source: str | None = None, churn: int = 0,
                  name_weak: bool = False, media_receiver: bool = False, mobile_service: bool = False,
                  mac_changes: int = 0) -> dict:
    """"Phone/tablet/laptop" score (see the module docstring).
    Returns {"mobile": bool, "score": int, "reason": main clue}."""
    score, reason = dhcp.mobile_score(mac, name_is_mobile, has_ports)
    score, reason = _name_clue(score, reason, name_is_mobile, name_weak)
    score, reason = _model_clue(score, reason, model_class)
    score, reason = _churn_clue(score, reason, mac, model_class, churn)
    score, reason = _mac_rotation_clue(score, reason, mac_changes)
    if mobile_service:
        score, reason = score + _W["mobile_service"], reason or "servizio mobile"  # announced only by phones and tablets
    # No listening service confirms any other clue (phones have none);
    # on its own it does not count: many IoT devices have no ports either.
    if has_ports is False and score > 0:
        score += _W["no_ports"]
    score, reason = _veto_clues(score, reason, media_receiver, battery, battery_source)
    return {"mobile": score >= MOBILE_THRESHOLD, "score": score, "reason": reason if score >= MOBILE_THRESHOLD else None,
            "threshold": MOBILE_THRESHOLD}


def _name_clue(score, reason, name_is_mobile, name_weak):
    """"Android" in the name (a weak clue) when the name is not already a phone-like one."""
    if name_weak and not name_is_mobile:
        return score + _W["name_weak"], reason or "nome"
    return score, reason


def _model_clue(score, reason, model_class):
    """The model class: mobile and laptop add points (and, if nothing else said it, are the reason), fixed takes points away."""
    if model_class == "mobile":
        return score + _W["model_mobile"], reason if score > 0 and reason else "model"
    if model_class == "laptop":
        return score + _W["model_laptop"], reason if score > 0 and reason else "model"
    if model_class == "fixed":
        return score + _W["model_fixed"], reason
    return score, reason


def _churn_clue(score, reason, mac, model_class, churn):
    # Online/offline alternation counts only with a private MAC (phones) or a recognized
    # laptop: a TV or a fixed PC, which are switched off every evening, have the manufacturer's MAC.
    if not (dhcp.is_private_mac(mac) or model_class == "laptop"):
        return score, reason
    if churn >= _CHURN_STRONG:
        return score + _W["churn_strong"], reason or "presence"
    if churn >= _CHURN_WEAK:
        return score + _W["churn_weak"], reason or "presence"
    return score, reason


def _mac_rotation_clue(score, reason, mac_changes):
    # Two or more different private MACs on the same card: a phone or tablet that rotates its Wi-Fi address. A new network
    # card has a global MAC, so a replaced PC does not count; a MAC lent by a repeater is left out by the history.
    if mac_changes >= 2:
        return score + _W["mac_rotation"], reason if reason not in (None, "MAC privato") else "MAC privati diversi"
    return score, reason


def _veto_clues(score, reason, media_receiver, battery, battery_source):
    """The negative clues: a device that plays video, or that is battery-powered but networked and fixed, is not a phone."""
    if media_receiver:
        score += _W["plays_video"]  # receives or plays video (cast, mirroring, renderer): TV, stick, box
        reason = None
    if battery == "yes" and battery_source in ("api", "scan", "hint"):
        score += _W["fixed_battery"]  # battery-powered but networked and fixed: not a phone
        reason = None
    return score, reason
