import re
from . import dhcp
from .adapters import ADAPTERS
from .formatters import quantize_uptime, should_show_title, wifi_quality, lan_quality, truncate_name
from . import brands
from .i18n import t_or as i18n_t_or
from .brands import match_model
from .identity import battery_assess, default_gateway, identify_brand, mobile_assess, presence_churn, presence_mac_changes

# Recognition by keyword in the name, not by MAC vendor: the
# vendor lookup is unreliable for phones (randomized MACs, see
# iPhone-di-Caio) and ambiguous anyway (Apple/Samsung also make laptops, TVs,
# monitors - not just phones). The device name (often auto-resolved
# via mDNS: "iPhone-di-Caio", "Xiaomi - MI14 di Sempronio") is the most
# direct signal actually available.
# "android" is not in the list: it is the operating system, not the device type (it also runs on
# TVs, sticks and boxes). It counts as a weak hint (see _MOBILE_NAME_WEAK).
_MOBILE_NAME_KEYWORDS = (
    "iphone", "ipad", "pixel", "galaxy", "xiaomi", "redmi",
    "oneplus", "huawei", "honor", "oppo", "vivo", "smartphone", "tablet",
    "telefono", "cellulare", "fairphone",
)


def _is_mobile(name: str | None) -> bool:
    return bool(name) and any(k in name.lower() for k in _MOBILE_NAME_KEYWORDS)


# Makers that only sell phones: the brand alone says "phone" (Xiaomi, Huawei... also sell TVs and routers: not here).
_PHONE_ONLY_BRANDS = ("fairphone", "murena")


def _phone_brand(brand: str | None) -> bool:
    return bool(brand) and any(k in brand.lower() for k in _PHONE_ONLY_BRANDS)


_MOBILE_NAME_WEAK = ("android",)
# "Declared" models that are actually the service type, not a model.
_GENERIC_MODELS = {"mediarenderer", "mediaserver", "basic", "dial", "device", "root"}
# What the device declares when it RECEIVES or PLAYS video (cast, mirroring,
# renderer): mDNS services, UPnP types, services and OS recognized by nmap.
# (no _airplay: Macs announce it too, and they are laptops)
_MEDIA_SERVICES = {"_googlecast._tcp", "_amzn-wplay._tcp", "_androidtvremote2._tcp"}
_MEDIA_UPNP = {"MediaRenderer", "dial"}
# mDNS services announced only by phones and tablets.
_MOBILE_SERVICES = {"_nearbypresence._tcp", "_apple-mobdev2._tcp"}
_MEDIA_TEXT = re.compile(r"tv\b|\btv|television", re.I)  # FireTV, AndroidTV, SmartTV, TV, tvOS: no brand


def _port_number(entry: dict) -> int | None:
    head = str(entry.get("label", "")).split(" ")[0]
    return int(head) if head.isdigit() else None


def _web_open(scanned_ports: list[dict]) -> bool | None:
    """True if an open port really serves a page for people, False if the ports were checked and none does,
    None if they were never checked (devices analysed before this check existed)."""
    checked = [p for p in scanned_ports if "web_ui" in p]
    if not checked:
        return None
    return any(p["web_ui"] for p in checked)


def _web_url(ip: str, port: int, scanned_ports: list[dict]) -> str:
    """Address of the "open web interface" button: the device's own port when it serves a real page, otherwise the
    best port that does (80 and 443 first), with https where the page needs it."""
    pages = [(p, _port_number(p)) for p in scanned_ports if p.get("web_ui")]
    pages = [(p, n) for p, n in pages if n is not None]
    if not pages:
        return f"http://{ip}:{port}"
    chosen = next((x for x in pages if x[1] == port), None) or min(pages, key=lambda x: (x[1] not in (80, 443), x[1]))
    entry, number = chosen
    return f"{entry.get('web_scheme') or 'http'}://{ip}:{number}"


def _media_receiver(ip: str, scan_info: dict, ports: list[dict]) -> bool:
    from . import roles  # late import
    services = set((scan_info.get("mdns_services") or "").replace(" ", "").split(","))
    if services & _MEDIA_SERVICES or _MEDIA_UPNP & set(roles.upnp_types(ip)):
        return True
    texts = [scan_info.get("upnp_model"), scan_info.get("mdns_model")]
    texts += [p.get("label") for p in ports if p.get("confirmed")]
    return any(_MEDIA_TEXT.search(t) for t in texts if t)


async def probe_device(device: dict, arp_task=None) -> dict:
    ip = device["ip"]
    port = device.get("port", 80)
    adapter_fn = ADAPTERS.get(device["adapter"])

    result = {"online": False}
    if adapter_fn:
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
    if arp_task is not None:
        arp_info = (await arp_task).get(ip)
        if arp_info:
            if not result.get("online"):
                result = {**result, "online": True}
            if not result.get("mac"):
                result["mac"] = arp_info.get("mac")

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

    mac = result.get("mac")
    extra = {k: v for k, v in result.get("extra", {}).items() if v}

    scan_info = device.get("scan_info") or {}
    # Remembered Bonjour names (continuous listening and past scans): they fill in what the scan did not find
    # because the device was asleep. Scan data, if present, wins.
    from . import mdns_listener
    remembered = mdns_listener.as_scan_info(mdns_listener.lookup(mac or device.get("last_mac"), ip))
    if remembered:
        scan_info = {**remembered, **{k: v for k, v in scan_info.items() if v}}
    from . import brands as _brands  # late import
    if _brands.is_bridge(scan_info.get("mdns_model")):
        # A proxy (AirCast, AirConnect...) announces the names of OTHER devices: they are not this one's.
        scan_info = {k: v for k, v in scan_info.items() if k not in ("mdns_name", "mdns_manufacturer")}
    if should_show_title(scan_info.get("http_title")) and "title" not in extra:
        extra["title"] = scan_info["http_title"]
    if scan_info.get("mdns_name") and scan_info["mdns_name"] != device.get("name") and "mdns" not in extra:
        extra["mdns"] = scan_info["mdns_name"]
    if scan_info.get("netbios_name") and scan_info["netbios_name"] != device.get("name") and "netbios" not in extra:
        extra["netbios"] = scan_info["netbios_name"]
    if scan_info.get("upnp_name") and scan_info["upnp_name"] != device.get("name") and "upnp_name" not in extra:
        extra["upnp_name"] = scan_info["upnp_name"]
    if scan_info.get("upnp_model") and "upnp_model" not in extra:
        extra["upnp_model"] = scan_info["upnp_model"]
    if scan_info.get("mdns_model") and "mdns_model" not in extra:
        extra["mdns_model"] = scan_info["mdns_model"]
    if scan_info.get("snmp_descr") and "snmp" not in extra:
        extra["snmp"] = scan_info["snmp_descr"]
    for key in ("upnp_manufacturer", "onvif_name", "onvif_hardware", "onvif_manufacturer", "rtsp_server",
                "api_vendor", "api_model", "api_fw", "tls_subject", "tls_issuer", "ssh_hostkey", "mdns_services", "igmp_groups",
                "http_server"):
        if scan_info.get(key) and key not in extra:
            extra[key] = scan_info[key]
    scanned_ports = scan_info.get("ports") or []
    identity_mac = mac or device.get("last_mac")
    dhcp_entry = dhcp.seen.get((identity_mac or "").lower())
    dhcp_name = (dhcp_entry or {}).get("hostname")
    dhcp_class = (dhcp_entry or {}).get("vendor_class")
    if dhcp_class and "dhcp_class" not in extra:
        extra["dhcp_class"] = dhcp_class   # e.g. "PS3", "MSFT 5.0", "android-dhcp-13"
    # The name chosen by the user wins; if the device is still named
    # after its IP (or has no name), the one it announces via DHCP is used.
    base_name = device.get("name") or result.get("name")
    from . import naming as _naming, ha_registry  # late imports
    ha_card = ha_registry.lookup(identity_mac, ip)
    # A system placeholder name ("Android_1MRKG1M7", random and different on every boot) is not a chosen
    # name: if another source provides a real one, it replaces it (and gets saved, see state._apply).
    placeholder = (not device.get("name_source") == "user") and _naming.is_placeholder(base_name)
    # Name taken from Home Assistant that HA no longer provides today (device linked by mistake or removed from HA):
    # it is recomputed from the other sources.
    ha_stale = device.get("name_source") in ("ha", "ha_user") and not ha_registry.choose_name(ha_card)[0]
    # Name taken from the page title that would no longer pass the checks today (e.g. the name of a software with its version).
    web_stale = device.get("name_source") == "web" and not _naming.title_name(scan_info.get("http_title"))
    ha_stale = ha_stale or web_stale
    placeholder = placeholder or ha_stale
    auto_name = None
    if not base_name or base_name == ip or placeholder:
        from . import naming, roles  # late imports
        found, _src = naming.pick([
            ("adapter", scan_info.get("api_name")), ("mdns", scan_info.get("mdns_name")),
            ("upnp", scan_info.get("upnp_name")), ("upnp", (roles.snapshot().get("names") or {}).get(ip)),
            ("dhcp", dhcp_name), ("netbios", scan_info.get("netbios_name")), ("onvif", scan_info.get("onvif_name")),
            ("tls", naming.cn_host(scan_info.get("tls_subject"))), ("web", naming.title_name(scan_info.get("http_title"))),
        ])
        if found and not (placeholder and _naming.is_placeholder(found)):
            was_ip = not base_name or base_name == ip
            base_name = found
            if placeholder or was_ip:   # it is saved: the name stays even when the source (e.g. a sleeping phone) goes silent
                auto_name = (found, _src, ha_stale)
        elif ha_stale:
            base_name = None   # no other source: better the default name than one from HA referring to another device
    # Home Assistant: the name the user gave there (or the integration's one) wins over weaker sources and
    # over placeholder names, never over a name chosen in Vedetta.
    ha_name, ha_src = ha_registry.choose_name(ha_card)
    # If the saved name was already taken from HA and it changed in HA, the change is followed (even with the same weight).
    from_ha = device.get("name_source") in ("ha", "ha_user")
    if ha_name and device.get("name_source") != "user" and ha_name != base_name \
            and (from_ha or _naming.is_better({"name": base_name, "ip": ip, "name_source": device.get("name_source")}, ha_src)):
        base_name = ha_name
        auto_name = (ha_name, ha_src, from_ha)
        placeholder = False
    # Leftover placeholder name ("Android", "iPhone"): it is not a name, the default name is tried first.
    kept_placeholder = base_name if (device.get("name_source") != "user" and _naming.is_placeholder(base_name)) else None
    display_name = ip if kept_placeholder else (truncate_name(base_name) or ip)
    if dhcp_name and dhcp_name != display_name and "dhcp" not in extra:
        extra["dhcp"] = dhcp_name

    # Brand, battery and "mobile" are decided in identity.py (multiple evidences with
    # source and confidence). The MAC prefix is only the maker of the network card: the
    # product brand comes from the device's own sources (UPnP/mDNS,
    # name, web title, DHCP fingerprint).
    shelly_model = (result.get("extra") or {}).get("model")
    models = [scan_info.get("mdns_model"), scan_info.get("upnp_model"), scan_info.get("onvif_hardware"),
              scan_info.get("api_model"), shelly_model, (ha_card or {}).get("model")]
    ident = identify_brand(
        identity_mac,
        names=[device.get("name"), dhcp_name, dhcp_class, scan_info.get("mdns_name"), scan_info.get("upnp_name"),
               scan_info.get("netbios_name"), scan_info.get("onvif_name"), scan_info.get("api_name"),
               (result.get("extra") or {}).get("hostname"), *models],
        upnp_manufacturer=scan_info.get("upnp_manufacturer"),
        declared=[scan_info.get("api_vendor"), scan_info.get("mdns_manufacturer"), scan_info.get("onvif_manufacturer"),
                  scan_info.get("onvif_hardware"), (ha_card or {}).get("manufacturer")],
        # Everything the device says about itself on the web: title, Server header and the
        # services recognized by nmap on its ports (e.g. "... REST API").
        web_text=" ".join(filter(None, [scan_info.get("http_title"), scan_info.get("http_server"), scan_info.get("rtsp_server"),
                                         scan_info.get("tls_subject"), scan_info.get("api_fw")]
                                  + [p.get("label") for p in scanned_ports])) or None,
        os_family=dhcp.os_family(identity_mac),
        is_gateway=ip == default_gateway(),
    )
    # Manufacturer declared by Home Assistant (integration): it counts more than MAC, name and web page; not if it is only the
    # chip maker ("Espressif") or if the device itself has already declared its brand.
    mfr = ((ha_card or {}).get("manufacturer") or "").strip()
    if mfr and ident.get("brand_source") not in ("declared", "user") and brands.vendor_role(mfr) != "component":
        ident = {**ident, "brand": brands.known_brand(mfr) or mfr, "brand_source": "ha", "brand_confidence": "high",
                 "brand_evidence": "confirmed"}
    # Manually chosen brand: it wins over any source and does not change with scans.
    if (device.get("brand_user") or "").strip():
        ident = {**ident, "brand": device["brand_user"].strip(), "brand_source": "user",
                 "brand_confidence": "high", "brand_evidence": "confirmed"}
    model_class = match_model([*models, dhcp_name, display_name])
    battery, battery_source = battery_assess(
        api=result.get("battery"), scan=scan_info.get("battery"), model_class=model_class,
        texts=[*models, scan_info.get("snmp_descr"), scan_info.get("http_title"), display_name])
    # The saved explicit choice (device["mobile"], set by hand in the edit
    # popup) always wins over the automatic score.
    explicit_mobile = device.get("mobile")
    assessment = None
    if explicit_mobile is not None:
        is_mobile = explicit_mobile
    else:
        scanned = bool(scan_info.get("scanned_at"))
        assessment = mobile_assess(
            mac=identity_mac, name_is_mobile=_is_mobile(display_name) or _phone_brand(ident.get("brand")),
            name_weak=any(k in (display_name or "").lower() for k in _MOBILE_NAME_WEAK),
            media_receiver=_media_receiver(ip, scan_info, scanned_ports),
            mobile_service=bool(_MOBILE_SERVICES & set((scan_info.get("mdns_services") or "").replace(" ", "").split(","))),
            has_ports=(not scanned_ports) if scanned else None, model_class=model_class,
            battery=battery, battery_source=battery_source,
            churn=presence_churn(device["id"]), mac_changes=presence_mac_changes(device["id"]))
        is_mobile = assessment["mobile"]
    if explicit_mobile is None and "mobile_app" in ((ha_card or {}).get("domains") or []):
        is_mobile = True   # the HA mobile app only exists on phones and tablets
    vendor, brand = ident["vendor"], ident["brand"]
    # No declared name: instead of the IP, "brand model" but only if BOTH are certain
    # (brand confirmed and model declared by the device). It is not saved: a name chosen
    # by the user, or a better automatic one, always prevails (naming.is_better).
    if display_name == ip and brand and ident.get("brand_evidence") == "confirmed":
        model = next((m for m in (scan_info.get("api_model"), scan_info.get("upnp_model"), scan_info.get("mdns_model"), (ha_card or {}).get("model"))
                      if m and m.lower() not in _GENERIC_MODELS and m.lower() != brand.lower()), None)
        if model:
            display_name = truncate_name(model if model.lower().startswith(brand.lower()) else f"{brand} {model}") or ip
    # Additional info: product brand and, if different, the board maker (chip).
    head = {k: v for k, v in (("brand", brand), ("vendor", vendor if vendor != brand else None)) if v and k not in extra}
    extra = {**head, **extra}
    if ha_card:   # Home Assistant: area, model and integration (additional attributes)
        for key, val in (("ha_area", ha_card.get("area")), ("ha_model", ha_card.get("model")),
                         ("ha_integration", ", ".join(ha_card.get("domains") or []))):
            if val:
                extra[key] = val

    # Still no name: brand + device type ("Milesight telecamera"), only if the brand is
    # known and the type is understood; otherwise the address stays. Never saved: any better name
    # (declared by the device or chosen by the user) prevails.
    generated_name = False   # name built by the app (brand + type...): must not count as a hint for the type
    if display_name == ip:
        from . import i18n, ha_data  # late imports
        probe_dev = {"ip": ip, "brand": brand, "vendor": vendor, "vendor_role": ident["vendor_role"],
                     "extra": extra, "scanned_ports": scanned_ports, "is_mobile": is_mobile, "ha_registry": ha_card}
        kind = ha_data.best_kind(probe_dev)
        label = i18n.t_or("kind." + kind, "") if kind else ""
        if not label:   # no precise type: the category name ("Apple telefono")
            label = i18n.t_or("group." + ha_data.infer_type(probe_dev), "")
        if label and ha_data.kind_is_product(kind):
            display_name = label  # "Home Assistant", "Raspberry Pi": the type is already the product
            generated_name = True
        elif brand and (ident["brand_source"] != "name" or ident["brand_evidence"] == "confirmed"):
            display_name = truncate_name(f"{brand} {label}".strip()) or ip  # a brand inferred only from a name is not enough
            generated_name = display_name != ip
    if display_name == ip and not kept_placeholder:
        # Still no name: the role the device plays on the network (detected via DNS, DHCP, UPnP, repeater)
        # tells what it is better than the address ("Server DNS").
        from . import roles as _roles  # late import
        found_roles = _roles.roles_for(ip)
        for role in ("gateway", "repeater", "ap", "dhcp", "dns"):
            if role in found_roles:
                label = i18n_t_or("rolename." + role, "")
                if label:
                    display_name = label
                    generated_name = True
                break
    if display_name == ip and kept_placeholder:
        display_name = truncate_name(kept_placeholder) or ip
    return {
        "ha_registry": ha_card,
        "name_generated": generated_name,
        "auto_name": auto_name,
        "id": device["id"],
        "name": display_name,
        "is_mobile": is_mobile,
        "mobile_score": assessment["score"] if assessment else None,       # for the evidence card
        "mobile_reason": assessment["reason"] if assessment else None,
        "ip": ip,
        "port": port,
        "url": _web_url(ip, port, scanned_ports),
        "web_open": _web_open(scanned_ports),
        "online": result.get("online", False),
        "uptime": quantize_uptime(result.get("uptime_seconds")),
        "mac": mac,
        "vendor": vendor,
        "vendor_role": ident["vendor_role"],
        "brand": brand,
        "brand_source": ident["brand_source"],
        "brand_confidence": ident["brand_confidence"],
        "brand_evidence": ident["brand_evidence"],
        "brand_declared": ident["brand_declared"],
        "battery": battery,
        "battery_source": battery_source,
        "signal_kind": signal_kind,
        "signal_value": signal_value,
        "signal_band": result.get("signal_band"),
        "signal_label": signal_label,
        "signal_color": signal_color,
        "extra": extra,
        "scanned_ports": scanned_ports,
        "scanned_at": scan_info.get("scanned_at"),
        "deep_empty_at": scan_info.get("deep_empty_at"),
    }
