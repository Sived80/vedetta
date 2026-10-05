import re
from . import dhcp
from .adapters import ADAPTERS
from .formatters import quantize_uptime, should_show_title, wifi_quality, lan_quality, truncate_name
from . import brands
from .i18n import t_or as i18n_t_or
from .brands import match_model
from .identity import battery_assess, default_gateway, identify_brand, mobile_assess, presence_churn

# Riconoscimento per parola chiave nel nome, non per produttore MAC: il
# vendor lookup e' inaffidabile per i telefoni (MAC randomizzati, vedi
# iPhone-di-Caio) e comunque ambiguo (Apple/Samsung fanno anche laptop, TV,
# monitor - non solo telefoni). Il nome del dispositivo (spesso auto-risolto
# via mDNS: "iPhone-di-Caio", "Xiaomi - MI14 di Sempronio") e' il segnale piu'
# diretto che si ha davvero a disposizione.
# "android" non c'e': e' il sistema operativo, non il tipo di apparecchio (gira anche su
# TV, chiavette e box). Vale come indizio debole (vedi _MOBILE_NAME_WEAK).
_MOBILE_NAME_KEYWORDS = (
    "iphone", "ipad", "pixel", "galaxy", "xiaomi", "redmi",
    "oneplus", "huawei", "honor", "oppo", "vivo", "smartphone", "tablet",
    "telefono", "cellulare",
)


def _is_mobile(name: str | None) -> bool:
    return bool(name) and any(k in name.lower() for k in _MOBILE_NAME_KEYWORDS)


_MOBILE_NAME_WEAK = ("android",)
# Modelli "dichiarati" che in realta' sono il tipo di servizio, non un modello.
_GENERIC_MODELS = {"mediarenderer", "mediaserver", "basic", "dial", "device", "root"}
# Cio' che il dispositivo dichiara quando RICEVE o RIPRODUCE video (cast, mirroring,
# renderer): servizi mDNS, tipi UPnP, servizi e sistema riconosciuti da nmap.
# (niente _airplay: lo annunciano anche i Mac, che sono portatili)
_MEDIA_SERVICES = {"_googlecast._tcp", "_amzn-wplay._tcp", "_androidtvremote2._tcp"}
_MEDIA_UPNP = {"MediaRenderer", "dial"}
# Servizi mDNS annunciati solo da telefoni e tablet.
_MOBILE_SERVICES = {"_nearbypresence._tcp", "_apple-mobdev2._tcp"}
_MEDIA_TEXT = re.compile(r"tv\b|\btv|television", re.I)  # FireTV, AndroidTV, SmartTV, TV, tvOS: nessuna marca


def _media_receiver(ip: str, scan_info: dict, ports: list[dict]) -> bool:
    from . import roles  # tardivo
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

    # L'ARP e' il segnale di presenza piu' affidabile su una LAN (pratica
    # consolidata: usato da arp-scan/Fing/Advanced IP Scanner, raccomandato
    # anche in progetti di home automation come Domoticz al posto del ping):
    # un dispositivo puo' bloccare ping e porte TCP (tipico di telefoni e
    # tablet) ma non puo' evitare di rispondere all'ARP se comunica affatto
    # sulla rete. Se l'adapter non l'ha trovato online ma compare nell'ultima
    # scansione ARP, vince l'ARP - mai il contrario (l'adapter puo' comunque
    # dare informazioni in piu' anche per un host visto "solo" via ARP).
    #
    # arp_task e' un asyncio.Task condiviso da tutti i dispositivi, avviato
    # PRIMA di iniziare i probe: cosi' la scansione ARP (~2s) gira in parallelo
    # con tutti i controlli invece che prima di essi in sequenza (altrimenti
    # ogni refresh pagina costava la somma dei due, non il piu' lento dei due -
    # verificato: 4.2s in sequenza contro 2.2s in parallelo).
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
    # Nomi Bonjour ricordati (ascolto continuo e scansioni passate): colmano cio' che la scansione non ha trovato
    # perche' il dispositivo dormiva. I dati della scansione, se ci sono, vincono.
    from . import mdns_listener
    remembered = mdns_listener.as_scan_info(mdns_listener.lookup(mac or device.get("last_mac"), ip))
    if remembered:
        scan_info = {**remembered, **{k: v for k, v in scan_info.items() if v}}
    from . import brands as _brands  # tardivo
    if _brands.is_bridge(scan_info.get("mdns_model")):
        # Un proxy (AirCast, AirConnect...) annuncia i nomi di ALTRI apparecchi: non sono di questo.
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
        extra["dhcp_class"] = dhcp_class   # es. "PS3", "MSFT 5.0", "android-dhcp-13"
    # Il nome scelto dall'utente vince; se il dispositivo e' ancora chiamato
    # come il suo IP (o non ha nome) si usa quello che annuncia via DHCP.
    base_name = device.get("name") or result.get("name")
    from . import naming as _naming, ha_registry  # tardivi
    ha_card = ha_registry.lookup(identity_mac, ip)
    # Un nome segnaposto del sistema ("Android_1MRKG1M7", casuale e diverso a ogni avvio) non e' un
    # nome scelto: se un'altra fonte ne da' uno vero, lo sostituisce (e si salva, vedi state._apply).
    placeholder = (not device.get("name_source") == "user") and _naming.is_placeholder(base_name)
    # Nome preso da Home Assistant che HA oggi non da' piu' (dispositivo agganciato per errore o rimosso da HA):
    # si ricalcola dalle altre fonti.
    ha_stale = device.get("name_source") in ("ha", "ha_user") and not ha_registry.choose_name(ha_card)[0]
    # Nome preso dal titolo della pagina che oggi non supererebbe piu' i controlli (es. nome di un software con la versione).
    web_stale = device.get("name_source") == "web" and not _naming.title_name(scan_info.get("http_title"))
    ha_stale = ha_stale or web_stale
    placeholder = placeholder or ha_stale
    auto_name = None
    if not base_name or base_name == ip or placeholder:
        from . import naming, roles  # tardivi
        found, _src = naming.pick([
            ("adapter", scan_info.get("api_name")), ("mdns", scan_info.get("mdns_name")),
            ("upnp", scan_info.get("upnp_name")), ("upnp", (roles.snapshot().get("names") or {}).get(ip)),
            ("dhcp", dhcp_name), ("netbios", scan_info.get("netbios_name")), ("onvif", scan_info.get("onvif_name")),
            ("tls", naming.cn_host(scan_info.get("tls_subject"))), ("web", naming.title_name(scan_info.get("http_title"))),
        ])
        if found and not (placeholder and _naming.is_placeholder(found)):
            was_ip = not base_name or base_name == ip
            base_name = found
            if placeholder or was_ip:   # si salva: il nome resta anche quando la fonte (es. un telefono che dorme) tace
                auto_name = (found, _src, ha_stale)
        elif ha_stale:
            base_name = None   # nessun'altra fonte: meglio il nome predefinito che uno di HA riferito a un altro dispositivo
    # Home Assistant: il nome che vi ha dato l'utente (o quello dell'integrazione) vince sulle fonti piu' deboli e
    # sui nomi segnaposto, mai su un nome scelto in Vedetta.
    ha_name, ha_src = ha_registry.choose_name(ha_card)
    # Se il nome salvato era gia' preso da HA e in HA e' cambiato, il cambio si segue (anche con lo stesso peso).
    from_ha = device.get("name_source") in ("ha", "ha_user")
    if ha_name and device.get("name_source") != "user" and ha_name != base_name \
            and (from_ha or _naming.is_better({"name": base_name, "ip": ip, "name_source": device.get("name_source")}, ha_src)):
        base_name = ha_name
        auto_name = (ha_name, ha_src, from_ha)
        placeholder = False
    # Nome segnaposto rimasto ("Android", "iPhone"): non e' un nome, si prova prima il nome predefinito.
    kept_placeholder = base_name if (device.get("name_source") != "user" and _naming.is_placeholder(base_name)) else None
    display_name = ip if kept_placeholder else (truncate_name(base_name) or ip)
    if dhcp_name and dhcp_name != display_name and "dhcp" not in extra:
        extra["dhcp"] = dhcp_name

    # Marca, batteria e "mobile" si decidono in identity.py (evidenze multiple con
    # fonte e confidenza). Il prefisso del MAC e' solo il produttore della scheda: la
    # marca del prodotto viene dalle fonti del dispositivo stesso (UPnP/mDNS,
    # nome, titolo web, impronta DHCP).
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
        # Tutto cio' che il dispositivo dice di se' sul web: titolo, intestazione Server e i
        # servizi riconosciuti da nmap sulle sue porte (es. "... REST API").
        web_text=" ".join(filter(None, [scan_info.get("http_title"), scan_info.get("http_server"), scan_info.get("rtsp_server"),
                                         scan_info.get("tls_subject"), scan_info.get("api_fw")]
                                  + [p.get("label") for p in scanned_ports])) or None,
        os_family=dhcp.os_family(identity_mac),
        is_gateway=ip == default_gateway(),
    )
    # Produttore dichiarato da Home Assistant (integrazione): vale piu' di MAC, nome e pagina web; non se e' solo il
    # produttore del chip ("Espressif") o se il dispositivo stesso ha gia' dichiarato la sua marca.
    mfr = ((ha_card or {}).get("manufacturer") or "").strip()
    if mfr and ident.get("brand_source") not in ("declared", "user") and brands.vendor_role(mfr) != "component":
        ident = {**ident, "brand": brands.known_brand(mfr) or mfr, "brand_source": "ha", "brand_confidence": "high",
                 "brand_evidence": "confirmed"}
    # Marca scelta a mano: vince su qualunque fonte e non cambia con le scansioni.
    if (device.get("brand_user") or "").strip():
        ident = {**ident, "brand": device["brand_user"].strip(), "brand_source": "user",
                 "brand_confidence": "high", "brand_evidence": "confirmed"}
    model_class = match_model([*models, dhcp_name, display_name])
    battery, battery_source = battery_assess(
        api=result.get("battery"), scan=scan_info.get("battery"), model_class=model_class,
        texts=[*models, scan_info.get("snmp_descr"), scan_info.get("http_title"), display_name])
    # La scelta esplicita salvata (device["mobile"], impostata a mano nel pop-up di
    # modifica) vince sempre sul punteggio automatico.
    explicit_mobile = device.get("mobile")
    if explicit_mobile is not None:
        is_mobile = explicit_mobile
    else:
        scanned = bool(scan_info.get("scanned_at"))
        is_mobile = mobile_assess(
            mac=identity_mac, name_is_mobile=_is_mobile(display_name),
            name_weak=any(k in (display_name or "").lower() for k in _MOBILE_NAME_WEAK),
            media_receiver=_media_receiver(ip, scan_info, scanned_ports),
            mobile_service=bool(_MOBILE_SERVICES & set((scan_info.get("mdns_services") or "").replace(" ", "").split(","))),
            has_ports=(not scanned_ports) if scanned else None, model_class=model_class,
            battery=battery, battery_source=battery_source,
            churn=presence_churn(device["id"]))["mobile"]
    if explicit_mobile is None and "mobile_app" in ((ha_card or {}).get("domains") or []):
        is_mobile = True   # l'app mobile di HA c'e' solo su telefoni e tablet
    vendor, brand = ident["vendor"], ident["brand"]
    # Nessun nome dichiarato: al posto dell'IP, "marca modello" ma solo se TUTTI E DUE sono certi
    # (marca confermata e modello dichiarato dal dispositivo). Non si salva: un nome scelto
    # dall'utente, o uno automatico migliore, prevale sempre (naming.is_better).
    if display_name == ip and brand and ident.get("brand_evidence") == "confirmed":
        model = next((m for m in (scan_info.get("api_model"), scan_info.get("upnp_model"), scan_info.get("mdns_model"), (ha_card or {}).get("model"))
                      if m and m.lower() not in _GENERIC_MODELS and m.lower() != brand.lower()), None)
        if model:
            display_name = truncate_name(model if model.lower().startswith(brand.lower()) else f"{brand} {model}") or ip
    # Info aggiuntive: marca del prodotto e, se diverso, produttore della scheda (chip).
    head = {k: v for k, v in (("brand", brand), ("vendor", vendor if vendor != brand else None)) if v and k not in extra}
    extra = {**head, **extra}
    if ha_card:   # Home Assistant: area, modello e integrazione (attributi aggiuntivi)
        for key, val in (("ha_area", ha_card.get("area")), ("ha_model", ha_card.get("model")),
                         ("ha_integration", ", ".join(ha_card.get("domains") or []))):
            if val:
                extra[key] = val

    # Ancora nessun nome: marca + tipo di apparecchio ("Milesight telecamera"), solo se la marca e'
    # nota e il tipo si capisce; altrimenti resta l'indirizzo. Mai salvato: ogni nome migliore
    # (dichiarato dal dispositivo o scelto dall'utente) prevale.
    generated_name = False   # nome costruito dall'app (marca + tipo...): non deve contare come indizio per il tipo
    if display_name == ip:
        from . import i18n, ha_data  # tardivi
        probe_dev = {"ip": ip, "brand": brand, "vendor": vendor, "vendor_role": ident["vendor_role"],
                     "extra": extra, "scanned_ports": scanned_ports, "is_mobile": is_mobile, "ha_registry": ha_card}
        kind = ha_data.best_kind(probe_dev)
        label = i18n.t_or("kind." + kind, "") if kind else ""
        if not label:   # nessun tipo preciso: il nome della categoria ("Apple telefono")
            label = i18n.t_or("group." + ha_data.infer_type(probe_dev), "")
        if label and ha_data.kind_is_product(kind):
            display_name = label  # "Home Assistant", "Raspberry Pi": il tipo e' gia' il prodotto
            generated_name = True
        elif brand and (ident["brand_source"] != "name" or ident["brand_evidence"] == "confirmed"):
            display_name = truncate_name(f"{brand} {label}".strip()) or ip  # una marca dedotta solo da un nome non basta
            generated_name = display_name != ip
    if display_name == ip and not kept_placeholder:
        # Ancora nessun nome: il ruolo che il dispositivo svolge in rete (rilevato con DNS, DHCP, UPnP, ripetitore)
        # dice cos'e' meglio dell'indirizzo ("Server DNS").
        from . import roles as _roles  # tardivo
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
        "ip": ip,
        "port": port,
        "url": f"http://{ip}:{port}",
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
    }
