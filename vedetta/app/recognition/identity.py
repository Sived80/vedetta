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
from ..scan import dhcp
from .vendor_lookup import is_private_mac, lookup_vendor
from .brands import normalize_brand

MOBILE_THRESHOLD = 3
CHURN_WINDOW_DAYS = 7
CHURN_REFRESH_S = 600
_CHURN_WEAK, _CHURN_STRONG = 6, 14

_NO_GATEWAY = object()
_gateway_cache: dict = {"value": _NO_GATEWAY}


def default_gateway(route_path: str = "/proc/net/route") -> str | None:
    """IP of the default gateway (from /proc/net/route, Linux); None if it cannot be read.
    Computed only once: a home LAN's gateway does not change."""
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
    """Two-level brand (see the module docstring). raw_vendor is the raw
    name from nmap/arp-scan, used only if the prefix database does not know the MAC."""
    vendor = lookup_vendor(mac)
    if vendor is None and raw_vendor and not is_private_mac(mac):
        vendor = normalize_brand(raw_vendor)
    found = brands.resolve(vendor, names=list(names), upnp_manufacturer=upnp_manufacturer, declared=declared,
                           web_text=web_text, os_family=os_family, is_gateway=is_gateway)
    role = found["role"] or ("private" if is_private_mac(mac) else None)
    source = found["source"]
    # Confirmed also when the chosen source is another one but the device declares the
    # same brand (e.g. name "SONY XR-55X92K" and UPnP manufacturer "Sony").
    declared_brands = {brands.known_brand(v) for v in (upnp_manufacturer, *declared) if v}
    if not found["brand"]:
        evidence = None
    elif source == "declared" or found["brand"] in declared_brands \
            or (source == "oui" and role == "brand" and not is_private_mac(mac))             or (role == "brand" and not is_private_mac(mac) and brands.known_brand(vendor) == found["brand"]):  # MAC and name agree
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
    now = time.time() if now is None else now
    if now - _churn["ts"] > CHURN_REFRESH_S:
        try:
            from ..storage.history import history  # late import: opens the database
            _churn["data"] = history.presence_flaps(now - CHURN_WINDOW_DAYS * 86400)
        except Exception:
            pass  # keep the last known value (or none)
        _churn["ts"] = now
    return _churn["data"].get(device_id, 0)


def presence_mac_changes(device_id: str, now: float | None = None) -> int:
    """How many different private MACs this card has used in the last 7 days (see History.private_mac_counts)."""
    now = time.time() if now is None else now
    if now - _macs["ts"] > CHURN_REFRESH_S:
        try:
            from ..storage.history import history
            _macs["data"] = history.private_mac_counts(now - CHURN_WINDOW_DAYS * 86400)
        except Exception:
            pass
        _macs["ts"] = now
    return _macs["data"].get(device_id, 0)


def mobile_assess(*, mac: str | None, name_is_mobile: bool, has_ports: bool | None,
                  model_class: str | None = None, battery: str | None = None,
                  battery_source: str | None = None, churn: int = 0,
                  name_weak: bool = False, media_receiver: bool = False, mobile_service: bool = False,
                  mac_changes: int = 0) -> dict:
    """"Phone/tablet/laptop" score (see the module docstring).
    Returns {"mobile": bool, "score": int, "reason": main clue}."""
    score, reason = dhcp.mobile_score(mac, name_is_mobile, has_ports)
    if name_weak and not name_is_mobile:
        score, reason = score + 2, reason or "nome"  # "Android" in the name: weak clue
    if model_class == "mobile":
        score, reason = score + 3, reason if score > 0 and reason else "model"
    elif model_class == "laptop":
        score, reason = score + 2, reason if score > 0 and reason else "model"
    elif model_class == "fixed":
        score -= 3
    # Online/offline alternation counts only with a private MAC (phones) or a recognized
    # laptop: a TV or a fixed PC, which are switched off every evening, have the manufacturer's MAC.
    if dhcp.is_private_mac(mac) or model_class == "laptop":
        if churn >= _CHURN_STRONG:
            score, reason = score + 2, reason or "presence"
        elif churn >= _CHURN_WEAK:
            score, reason = score + 1, reason or "presence"
    # Two or more different private MACs on the same card: a phone or tablet that rotates its Wi-Fi address. A new network
    # card has a global MAC, so a replaced PC does not count; a MAC lent by a repeater is left out by the history.
    if mac_changes >= 2:
        score, reason = score + 3, reason if reason not in (None, "MAC privato") else "MAC privati diversi"
    if mobile_service:
        score, reason = score + 3, reason or "servizio mobile"  # announced only by phones and tablets
    # No listening service confirms any other clue (phones have none);
    # on its own it does not count: many IoT devices have no ports either.
    if has_ports is False and score > 0:
        score += 1
    if media_receiver:
        score -= 4  # receives or plays video (cast, mirroring, renderer): TV, stick, box
        reason = None
    if battery == "yes" and battery_source in ("api", "scan", "hint"):
        score -= 4  # battery-powered but networked and fixed: not a phone
        reason = None
    return {"mobile": score >= MOBILE_THRESHOLD, "score": score, "reason": reason if score >= MOBILE_THRESHOLD else None,
            "threshold": MOBILE_THRESHOLD}
