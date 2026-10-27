"""Builds the card of ONE device (probe_device): asks its adapter, adds what the search, Bonjour, DHCP and Home Assistant know, decides name, brand and "mobile", and
returns a single record. The decisions about names are in probe_names, the web address in probe_web."""
import re
from . import dhcp, presence, touch_policy
from .probe_record import Brand, Facts, Naming, Signal, _build_probe_record
from .adapters import ADAPTERS
from ..formatters import should_show_title, wifi_quality, lan_quality
from ..recognition import brands, naming
from ..ha import ha_registry
from . import mdns_listener
from ..i18n import t_or as i18n_t_or
from ..recognition.brands import match_model
from ..recognition.identity import battery_assess, default_gateway, identify_brand, mobile_assess, presence_churn, presence_mac_changes
from ..recognition import roles
from .probe_names import _GENERIC_MODELS, _add_announced_name_extras, _add_declared_service_extras, NameState, choose_automatic_name, name_from_brand_and_model, name_from_brand_and_type, name_from_network_role, prefer_home_assistant_name  # noqa: F401
from .probe_web import _unverified_url, _verified_pages, _web_open, _web_url  # noqa: F401

_MOBILE_NAME_WEAK = ("android",)
# What the device declares when it RECEIVES or PLAYS video (cast, mirroring,
# renderer): mDNS services, UPnP types, services and OS recognized by nmap.
# (no _airplay: Macs announce it too, and they are laptops)
_MEDIA_SERVICES = {"_googlecast._tcp", "_amzn-wplay._tcp", "_androidtvremote2._tcp"}
_MEDIA_UPNP = {"MediaRenderer", "dial"}
# mDNS services announced only by phones and tablets.
_MOBILE_SERVICES = {"_nearbypresence._tcp", "_apple-mobdev2._tcp"}
_MEDIA_TEXT = re.compile(r"tv\b|\btv|television", re.IGNORECASE)  # FireTV, AndroidTV, SmartTV, TV, tvOS: no brand


async def probe_device(device: dict, arp_task=None) -> dict:
    ip, port, result = await _probe_device_gather(device, arp_task)
    signal = Signal(*_probe_device_signal(result, device))
    f = _read_facts(device, ip, port, result)
    base_name = device.get("name") or result.get("name")
    placeholder, ha_stale = _stale_name(f, base_name)
    names = NameState(base_name, placeholder, ha_stale)
    choose_automatic_name(f, names, dhcp.fingerprint_family(f.identity_mac))
    prefer_home_assistant_name(f, names)
    brand_stage = _probe_device_brand(f, names.display_name)
    assessment, is_mobile = _probe_device_mobile(f, names.display_name, brand_stage)
    product = name_from_brand_and_model(f, names, brand_stage.ident)
    name_from_brand_and_type(f, names, product, brand_stage.ident, is_mobile)
    name_from_network_role(f, names)
    return _build_probe_record(f, signal, brand_stage, Naming(names.display_name, names.kept_placeholder, names.generated, names.auto_name), product, assessment, is_mobile)


async def _probe_device_gather(device, arp_task):
    ip = device["ip"]
    port = device.get("port", 80)
    adapter_fn = ADAPTERS.get(device["adapter"])

    result = {"online": False}
    if adapter_fn and touch_policy.may_touch(device):   # a device that must not be touched is not asked: ARP alone says if it is there
        try:
            result = await adapter_fn(ip, port)
        except Exception:
            result = {"online": False}

    # ARP is the most reliable presence signal on a LAN (established practice:
    # used by arp-scan/Fing/Advanced IP Scanner, also recommended in home
    # automation projects such as Domoticz instead of ping):
    # a device can block ping and TCP ports (typical of phones and
    # tablets) but cannot avoid answering ARP if it communicates at all on the
    # network. If the adapter did not find it online but it appears in the latest
    # ARP scan, ARP wins - never the other way around (the adapter can still
    # provide extra information even for a host seen "only" via ARP).
    #
    # arp_task is an asyncio.Task shared by all devices, started
    # BEFORE the probes begin: this way the ARP scan (~2s) runs in parallel
    # with all the checks instead of before them in sequence (otherwise
    # every page refresh cost the sum of the two, not the slower of the two -
    # verified: 4.2s in sequence versus 2.2s in parallel).
    result = await presence.complete_with_arp(result, device, ip, arp_task)
    return ip, port, result


def _probe_device_signal(result, device):
    signal_label = None            # set below on some paths only
    signal_color = None            # set below on some paths only
    signal_kind = result.get("signal_kind")
    signal_value = result.get("signal_value")

    lan_speed = device.get("lan_speed_mbps")
    if signal_kind is None and result.get("online") and lan_speed is not None:
        signal_kind = "lan"
        signal_value = f"{lan_speed} Mbps"

    if signal_kind == "wifi":
        signal_label, signal_color = wifi_quality(result.get("signal_value"))
    elif signal_kind == "lan":
        signal_label, signal_color = lan_quality(lan_speed)
    else:
        signal_label, signal_color = None, None
    return signal_kind, signal_value, signal_label, signal_color


def _read_facts(device, ip, port, result) -> Facts:
    """Everything the later decisions need to know: what the search and Bonjour remember (the announced names and the declared services are added to `extra`), the MAC the
    memories are asked with, what DHCP and Home Assistant say about it."""
    mac, extra, scan_info = _merge_remembered_mdns_info(result, ip, device)
    _add_announced_name_extras(extra, scan_info, device)
    key = _add_declared_service_extras(extra, scan_info)
    identity_mac = mac or device.get("last_mac")
    dhcp_entry = dhcp.seen.get((identity_mac or "").lower())
    dhcp_name = (dhcp_entry or {}).get("hostname")
    dhcp_class = (dhcp_entry or {}).get("vendor_class")
    if dhcp_class and "dhcp_class" not in extra:
        extra["dhcp_class"] = dhcp_class   # e.g. "PS3", "MSFT 5.0", "android-dhcp-13"
    return Facts(device=device, ip=ip, port=port, result=result, mac=mac, extra=extra, scan_info=scan_info, scanned_ports=scan_info.get("ports") or [], identity_mac=identity_mac,
                 dhcp_name=dhcp_name, dhcp_class=dhcp_class, ha_card=ha_registry.lookup(identity_mac, ip), key=key)


def _merge_remembered_mdns_info(result, ip, device):
    mac = result.get("mac")
    extra = {k: v for k, v in result.get("extra", {}).items() if v}
    scan_info = _with_remembered_mdns(device.get("scan_info") or {}, mac, ip, device)
    if should_show_title(scan_info.get("http_title")) and "title" not in extra:
        extra["title"] = scan_info["http_title"]
    return mac, extra, scan_info


def _with_remembered_mdns(scan_info, mac, ip, device):
    """Remembered Bonjour names (continuous listening and past scans) fill in what the scan did not find because the device was asleep.
    Scan data, if present, wins. The names of a proxy (AirCast, AirConnect...) are those of OTHER devices: they are dropped."""
    remembered = mdns_listener.as_scan_info(mdns_listener.lookup(mac or device.get("last_mac"), ip))
    if remembered:
        scan_info = {**remembered, **{k: v for k, v in scan_info.items() if v}}
    if brands.is_bridge(scan_info.get("mdns_model")):
        scan_info = {k: v for k, v in scan_info.items() if k not in ("mdns_name", "mdns_manufacturer")}
    return scan_info


def _stale_name(f: Facts, base_name):
    """(placeholder, ha_stale): the name must be recomputed from the other sources.
    A system placeholder name ("Android_1MRKG1M7", random on every boot) is not a chosen name. A name taken from Home Assistant that HA no longer
    provides (device linked by mistake or removed from HA), or from a page title that would no longer pass the checks today, is stale too."""
    source = f.device.get("name_source")
    placeholder = (source != "user") and naming.is_placeholder(base_name)
    ha_stale = source in ("ha", "ha_user") and not ha_registry.choose_name(f.ha_card)[0]
    web_stale = source == "web" and not naming.title_name(f.scan_info.get("http_title"))
    ha_stale = ha_stale or web_stale
    return placeholder or ha_stale, ha_stale


def _probe_device_brand(f: Facts, display_name) -> Brand:
    # Brand, battery and "mobile" are decided in identity.py (multiple evidences with
    # source and confidence). The MAC prefix is only the maker of the network card: the
    # product brand comes from the device's own sources (UPnP/mDNS,
    # name, web title, DHCP fingerprint).
    info, card = f.scan_info, f.ha_card
    shelly_model = (f.result.get("extra") or {}).get("model")
    models = [info.get("mdns_model"), info.get("upnp_model"), info.get("onvif_hardware"),
              info.get("api_model"), shelly_model, (card or {}).get("model")]
    ident = identify_brand(
        f.identity_mac,
        names=[f.device.get("name"), f.dhcp_name, f.dhcp_class, info.get("mdns_name"), info.get("upnp_name"),
               info.get("netbios_name"), info.get("onvif_name"), info.get("api_name"),
               (f.result.get("extra") or {}).get("hostname"), *models],
        upnp_manufacturer=info.get("upnp_manufacturer"),
        declared=[info.get("api_vendor"), info.get("mdns_manufacturer"), info.get("onvif_manufacturer"),
                  info.get("onvif_hardware"), (card or {}).get("manufacturer")],
        web_text=_web_text(info, f.scanned_ports),
        os_family=dhcp.os_family(f.identity_mac),
        is_gateway=f.ip == default_gateway(),
    )
    ident = _chosen_brand(ident, card, f.device)
    model_class = match_model([*models, f.dhcp_name, display_name])
    battery, battery_source = battery_assess(
        api=f.result.get("battery"), scan=info.get("battery"), model_class=model_class,
        texts=[*models, info.get("snmp_descr"), info.get("http_title"), display_name])
    return Brand(ident, model_class, battery, battery_source)


def _web_text(scan_info, scanned_ports):
    """Everything the device says about itself on the web: title, Server header and the services recognized by nmap on its ports (e.g. "... REST API")."""
    return " ".join(filter(None, [scan_info.get("http_title"), scan_info.get("http_server"), scan_info.get("rtsp_server"),
                                  scan_info.get("tls_subject"), scan_info.get("api_fw")]
                           + [p.get("label") for p in scanned_ports])) or None


def _chosen_brand(ident, ha_card, device):
    """The brand declared by Home Assistant (integration) counts more than MAC, name and web page; not if it is only the chip maker ("Espressif")
    or if the device itself has already declared its brand. A manually chosen brand wins over any source and does not change with scans."""
    mfr = ((ha_card or {}).get("manufacturer") or "").strip()
    if mfr and ident.get("brand_source") not in ("declared", "user") and brands.vendor_role(mfr) != "component":
        ident = {**ident, "brand": brands.known_brand(mfr) or mfr, "brand_source": "ha", "brand_confidence": "high",
                 "brand_evidence": "confirmed"}
    if (device.get("brand_user") or "").strip():
        ident = {**ident, "brand": device["brand_user"].strip(), "brand_source": "user",
                 "brand_confidence": "high", "brand_evidence": "confirmed"}
    return ident


def _probe_device_mobile(f: Facts, display_name, brand_stage: Brand):
    # The saved explicit choice (device["mobile"], set by hand in the edit
    # popup) always wins over the automatic score.
    explicit_mobile = f.device.get("mobile")
    if explicit_mobile is not None:
        return None, explicit_mobile
    assessment = _mobile_score(f, display_name, brand_stage)
    # The HA mobile app only exists on phones and tablets.
    is_mobile = True if "mobile_app" in ((f.ha_card or {}).get("domains") or []) else assessment["mobile"]
    return assessment, is_mobile


def _mobile_score(f: Facts, display_name, brand_stage: Brand):
    """The automatic assessment: mobile or fixed, from the name, the services, the ports, the battery and how often it comes and goes."""
    scanned = bool(f.scan_info.get("scanned_at"))
    return mobile_assess(
        mac=f.identity_mac, name_is_mobile=_is_mobile(display_name) or _is_mobile(f.dhcp_name) or brands.is_phone_only(brand_stage.ident.get("brand")),
        name_weak=any(k in (display_name or "").lower() for k in _MOBILE_NAME_WEAK),
        media_receiver=_media_receiver(f.ip, f.scan_info, f.scanned_ports),
        mobile_service=bool(_MOBILE_SERVICES & set((f.scan_info.get("mdns_services") or "").replace(" ", "").split(","))),
        has_ports=(not f.scanned_ports) if scanned else None, model_class=brand_stage.model_class,
        battery=brand_stage.battery, battery_source=brand_stage.battery_source,
        churn=presence_churn(f.device["id"]), mac_changes=presence_mac_changes(f.device["id"]))


def _is_mobile(name: str | None) -> bool:
    return bool(name) and any(k in name.lower() for k in brands.mobile_name_words())


def _media_receiver(ip: str, scan_info: dict, ports: list[dict]) -> bool:
    services = set((scan_info.get("mdns_services") or "").replace(" ", "").split(","))
    if services & _MEDIA_SERVICES or _MEDIA_UPNP & set(roles.upnp_types(ip)):
        return True
    texts = [scan_info.get("upnp_model"), scan_info.get("mdns_model")]
    texts += [p.get("label") for p in ports if p.get("confirmed")]
    return any(_MEDIA_TEXT.search(t) for t in texts if t)
