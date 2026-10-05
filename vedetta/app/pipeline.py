"""Flusso unico delle ricerche: funzioni (step) indipendenti attivate dai profili.

Registro e default in flows.py, scelte dell'utente in settings.json (chiave
"flows"), letti a ogni esecuzione: cambiare impostazione vale dalla scansione
successiva, senza riavvio.

Mappa funzione -> primitive in scanner.py:
  arp            scanner.arp_scan             scoperta host (solo profilo initial)
  mdns           scanner.mdns_scan            nomi Bonjour/Avahi passivi
  reverse_names  scanner.resolve_mdns_name    risoluzione inversa avahi, per IP senza nome
  ssdp           scanner.ssdp_scan            UPnP (una volta per l'intero lotto)
  netbios_snmp   scanner.protocol_scan        NetBIOS/SNMP (nmap -sU leggero)
  ports_fast     (flag nmap)                  -p- con host-timeout 30s
  ports_all      (flag nmap)                  -p- con host-timeout 150s
  service_os     (flag nmap)                  -sV --version-light
  http_title     (flag nmap + GET diretta)    --script http-title (con service_os) e
                                              conferma HTTP delle porte (_confirm_http_ports)
  adapter_probe  adapter shelly_gen1.probe    riconoscimento Shelly sulla porta 80

Gli step che sono flag dello stesso nmap si compongono in UNA sola invocazione
(compose_nmap_args). Uno step che dipende dall'output di un altro (http_title e
adapter_probe hanno bisogno delle porte) se manca la dipendenza si salta con un
log INFO, senza errori."""
import asyncio
import time
from dataclasses import dataclass, field

from . import dhcp, discovery, flows, localapi, naming, scanner, settings
from .adapters import shelly_gen1, shelly_gen2
from .applog import logger
from .formatters import truncate_name
from .netutil import get_local_network
from .vendor_lookup import resolve_vendor_info

# Step che producono l'elenco delle porte (una invocazione nmap TCP).
NMAP_PORT_STEPS = ("ports_fast", "ports_all", "service_os")
# Step che hanno bisogno delle porte gia' trovate.
NEEDS_PORTS = ("http_title", "adapter_probe", "tls_ssh")

_EMPTY_HOST = {"mac": None, "hostname": None, "ports": [], "http_title": None}


def active_steps(profile: str) -> list[str]:
    """Step attivi del profilo, riletti dalle impostazioni a ogni chiamata."""
    return settings.flows_load()[profile]


def compose_nmap_args(steps, ip: str, slow: bool = False) -> list[str] | None:
    """UNA sola invocazione nmap per gli step attivi, oppure None se nessuno
    step ne richiede una (nessuna scansione TCP).

    Con tutti gli step ottiene esattamente la vecchia scansione approfondita
    (-T4 -sV --version-light --host-timeout 150s --script http-title -p-),
    con ports_fast da solo la vecchia scansione rapida (-T4 -p- --host-timeout 30s).
    -T4 e' la velocita' raccomandata da nmap per LAN affidabili; -sV senza
    --version-light puo' impiegare quasi 100s su una singola porta difficile
    (verificato), e senza -sV la scansione -p- costa quanto un elenco fisso,
    quindi si usa sempre -p- e mai --top-ports (che escluderebbe porte da
    homelab come 8006/Proxmox o 8123/Home Assistant). Il timeout e' lungo (150s)
    se c'e' una scansione pesante (ports_all/service_os), breve (30s) per il
    solo rilevamento rapido. --script http-title viaggia insieme a service_os
    (come nella vecchia scansione approfondita): da sola sulle porte rapide
    costerebbe tempo che la ricerca associativa non ha mai speso."""
    chosen = set(steps)
    if not chosen & set(NMAP_PORT_STEPS):
        return None
    args = ["-T4"]
    heavy = bool(chosen & {"ports_all", "service_os"})
    if "service_os" in chosen:
        args += ["-sV", "--version-light"]
    args += ["--host-timeout", "150s" if heavy else "30s"]
    if "service_os" in chosen and "http_title" in chosen:
        args += ["--script", "http-title"]
    if chosen & {"ports_fast", "ports_all"}:
        args.append("-p-")
    if slow and "-p-" in args:
        # Dispositivo lento (la scansione di tutte le porte e' scaduta in passato): porte
        # mirate e tempo massimo ridotto, invece di restare in coda per minuti.
        args[args.index("-p-"):args.index("-p-") + 1] = ["-p", scanner.FAST_PORTS]
        args[args.index("--host-timeout") + 1] = "60s"
    args.append(ip)
    return args


def resolve_plan(steps) -> tuple[list[str], list[tuple[str, str]]]:
    """(step eseguibili, [(step saltato, motivo)]): salta chi dipende da un
    output che nessuno step attivo produce."""
    chosen = set(steps)
    has_ports = bool(chosen & set(NMAP_PORT_STEPS))
    run, skipped = [], []
    for step_id in flows.STEP_IDS:
        if step_id not in chosen:
            continue
        if step_id in NEEDS_PORTS and not has_ports:
            skipped.append((step_id, "richiede le porte (ports_fast, ports_all o service_os)"))
        else:
            run.append(step_id)
    return run, skipped


def _log_skipped(skipped: list[tuple[str, str]], where: str) -> None:
    for step_id, reason in skipped:
        logger.info("%s: funzione '%s' saltata, %s", where, step_id, reason)


@dataclass
class Batch:
    """Risultati condivisi da un lotto di dispositivi (calcolati una sola volta:
    mDNS e SSDP sono broadcast di tutta la LAN, non per singolo host)."""
    steps: list[str]
    mdns_names: dict[str, str] = field(default_factory=dict)
    upnp_info: dict[str, dict] = field(default_factory=dict)
    wsd_info: dict[str, dict] = field(default_factory=dict)
    igmp_info: dict[str, list] = field(default_factory=dict)


async def _names_for(steps, ips: list[str]) -> dict[str, str]:
    """Nomi da mdns (passivo, una chiamata per tutta la rete) e/o reverse_names
    (query attiva mirata sugli IP rimasti senza nome)."""
    chosen = set(steps)
    if "mdns" in chosen and "reverse_names" in chosen:
        return await scanner.resolve_names(ips)
    if "mdns" in chosen:
        return await scanner.mdns_scan()
    if "reverse_names" in chosen:
        return await scanner.resolve_names(ips, passive_names={})
    return {}


async def prepare_batch(profile: str, ips: list[str], steps: list[str] | None = None) -> Batch:
    """Parte "di lotto" del profilo: nomi mDNS/inversi e SSDP, una volta sola
    per tutti gli IP, in parallelo. Un errore qui non ferma la scansione: si
    prosegue senza quel dato."""
    steps = list(steps) if steps is not None else active_steps(profile)
    batch = Batch(steps=steps)
    jobs = {}
    if {"mdns", "reverse_names"} & set(steps):
        jobs["names"] = _names_for(steps, ips)
    if "ssdp" in steps:
        jobs["ssdp"] = scanner.ssdp_scan()
    if "onvif" in steps:
        jobs["onvif"] = _wsd()
    if "igmp" in steps:
        jobs["igmp"] = scanner.igmp_scan()
    if not jobs:
        return batch
    results = await asyncio.gather(*jobs.values(), return_exceptions=True)
    for key, result in zip(jobs, results):
        if isinstance(result, Exception):
            logger.error("Funzione '%s' fallita: %r", key, result)
            continue
        if key == "names":
            batch.mdns_names = result
        elif key == "onvif":
            batch.wsd_info = result
        elif key == "igmp":
            batch.igmp_info = result
        else:
            batch.upnp_info = result
    return batch


async def _wsd() -> dict[str, dict]:
    try:
        _, own_ip = await get_local_network()
    except Exception:
        own_ip = None
    return await discovery.wsd_scan(own_ip)


async def scan_host(ip: str, batch: Batch, slow: bool = False) -> dict:
    """Funzioni "per host" del profilo (nmap composto, NetBIOS/SNMP, conferma
    porte web, adapter) e unione con i dati di lotto. Ritorna lo stesso dict che
    produceva full_scan (piu' le chiavi 'adapter'/'adapter_extra')."""
    steps = batch.steps
    run, skipped = resolve_plan(steps)
    _log_skipped(skipped, ip)
    chosen = set(run)

    # Il nmap TCP e il nmap UDP (NetBIOS/SNMP) sono processi separati lanciati in
    # parallelo, non uno dopo l'altro: non si sommano ai tempi gia' lunghi di -p- -sV.
    nmap_args = compose_nmap_args(run, ip, slow)
    # Prima si misura se il dispositivo regge la scansione di tutte le porte (prova pilota
    # su 1000): se e' lento si passa subito alle porte mirate, senza aspettare i 150 s.
    if nmap_args and "-p-" in nmap_args:
        try:
            probe = await scanner.pilot(ip)
        except Exception as exc:
            logger.info("%s: prova pilota fallita (%r), scansione normale", ip, exc)
            probe = None
        if probe and probe["slow"]:
            logger.info("%s: dispositivo lento (1000 porte in %.1fs), scansione mirata invece di tutte le porte", ip, probe["elapsed"])
            slow = True
            nmap_args = compose_nmap_args(run, ip, True)
    nmap_job = scanner._run_nmap(nmap_args) if nmap_args else None
    proto_job = scanner.protocol_scan(ip) if "netbios_snmp" in chosen else None
    rtsp_job = discovery.rtsp_probe(ip) if "rtsp" in chosen else None
    jobs = [j for j in (nmap_job, proto_job, rtsp_job) if j is not None]
    results = await asyncio.gather(*jobs) if jobs else []
    xml_text = results.pop(0) if nmap_job is not None else None
    protocol_info = results.pop(0) if proto_job is not None else {}
    rtsp_info = results.pop(0) if rtsp_job is not None else {}

    hosts = scanner._parse_hosts(xml_text) if xml_text is not None else []
    info = hosts[0] if hosts else {"ip": ip, **_EMPTY_HOST}
    # La scansione e' scaduta e nmap ha scartato le porte: scansione mirata di ripiego, e
    # il dispositivo si segna come lento per le volte successive.
    if ip in scanner.timed_out:
        scanner.timed_out.discard(ip)
        info["slow_scan"] = True
        if not info["ports"]:
            try:
                fast = await scanner.fast_ports(ip)
            except Exception as exc:
                logger.info("%s: scansione mirata di ripiego fallita (%r)", ip, exc)
                fast = None
            if fast and fast.get("ports"):
                info["ports"] = fast["ports"]
                info["http_title"] = info.get("http_title") or fast.get("http_title")
                logger.info("%s: scansione completa scaduta, %d porte trovate con la scansione mirata", ip, len(fast["ports"]))
    elif slow:
        info["slow_scan"] = True
    info["mdns_name"] = batch.mdns_names.get(ip)
    # Modello/produttore annunciati via mDNS TXT (_device-info, AirPlay, Chromecast...).
    meta = scanner.mdns_meta.get(ip) or {}
    if meta.get("model"):
        info["mdns_model"] = meta["model"]
    if meta.get("manufacturer"):
        info["mdns_manufacturer"] = meta["manufacturer"]
    info.update(protocol_info)
    upnp = batch.upnp_info.get(ip) if "ssdp" in chosen else None
    if upnp:
        if upnp.get("name"):
            info["upnp_name"] = upnp["name"]
        if upnp.get("manufacturer"):
            info["upnp_manufacturer"] = upnp["manufacturer"]
        if upnp.get("model"):
            info["upnp_model"] = upnp["model"]

    # Auto-dichiarazione ONVIF/WS-Discovery e intestazione Server di RTSP.
    wsd = batch.wsd_info.get(ip) if "onvif" in chosen else None
    if wsd:
        for key in ("name", "hardware", "manufacturer"):
            if wsd.get(key):
                info["onvif_" + key] = wsd[key]
        if wsd.get("types"):
            info["wsd_types"] = ", ".join(wsd["types"])[:120]
    if rtsp_info.get("rtsp_server"):
        info["rtsp_server"] = rtsp_info["rtsp_server"]
    if meta.get("services"):
        info["mdns_services"] = ", ".join(meta["services"])[:200]
    if "igmp" in chosen and batch.igmp_info.get(ip):
        info["igmp_groups"] = ", ".join(batch.igmp_info[ip][:6])
    # Certificato TLS e chiave SSH: un secondo nmap leggero solo sulle porte gia' trovate
    # aperte (dentro la scansione -p- gli script la allungavano oltre il suo timeout).
    if "tls_ssh" in chosen and info["ports"]:
        try:
            info.update(await scanner.tls_ssh_scan(ip, info["ports"]))
        except Exception as exc:
            logger.info("%s: certificato/chiave non letti (%r)", ip, exc)
    if "local_api" in chosen:
        # Senza porte note (dispositivi lenti che superano il timeout di nmap) si prova
        # comunque la porta 80: e' una sola GET documentata, con timeout breve.
        try:
            info.update(await localapi.probe(ip, [p["port"] for p in info["ports"]] or [80]))
        except Exception as exc:
            logger.info("%s: interfaccia locale non letta (%r)", ip, exc)

    if "http_title" in chosen:
        await scanner._confirm_http_ports(ip, info["ports"])
        # Server e titolo trovati dalla GET: servono a riconoscere cosa e'
        # (titolo di nmap, se c'e', ha la precedenza).
        found = scanner.web_identity(info["ports"])
        if found.get("http_server"):
            info["http_server"] = found["http_server"]
        if found.get("http_title") and not info.get("http_title"):
            info["http_title"] = found["http_title"]
        if found.get("tls_subject") and not info.get("tls_subject"):
            info["tls_subject"] = found["tls_subject"]

    adapter, extra = "generic", {}
    if "adapter_probe" in chosen and any(p["port"] == 80 for p in info["ports"]):
        try:
            result = await shelly_gen1.probe(ip, 80)
        except Exception:
            result = {}
        # Solo se la risposta ha davvero la forma dell'API Shelly (mac + uptime),
        # altrimenti un qualunque webserver su porta 80 finirebbe classificato come Shelly.
        if result.get("mac") and result.get("uptime_seconds") is not None:
            adapter = "shelly_gen1"
            extra = result
            info["battery"] = "yes" if result.get("battery") else "no"
        elif result.get("mac") is None:
            # Non e' un Gen1: forse un Gen2+ (API RPC), dove "devicepower" rivela la batteria.
            try:
                gen2 = await shelly_gen2.battery_probe(ip, 80)
            except Exception:
                gen2 = {}
            if gen2:
                info["battery"] = "yes" if gen2.get("battery") else "no"
    info["adapter"] = adapter
    info["adapter_extra"] = extra
    return info


# ---- profilo initial: ricerca iniziale ----
def _dhcp_hostname(mac: str | None) -> str | None:
    return (dhcp.seen.get((mac or "").lower()) or {}).get("hostname")


async def run_initial() -> list[dict]:
    """Scoperta host: solo ARP, quindi IP e MAC (e il produttore del MAC). Nessuna ricerca di
    nomi: l'unico nome che passa e' quello DHCP gia' ascoltato, tenuto come suggerimento
    interno per l'analisi che parte all'aggiunta (non si mostra)."""
    logger.info("Avviata: scansione ARP (tutta la LAN)")
    t0 = time.monotonic()
    arp_hosts = await scanner.arp_scan()
    try:
        _, own_ip = await get_local_network()
    except Exception:
        own_ip = None
    me = scanner.own_host(own_ip, arp_hosts)
    if me:
        arp_hosts.append(me)
    logger.info("Completata (%.1fs): scansione ARP, %d host trovati", time.monotonic() - t0, len(arp_hosts))
    hosts = []
    for h in arp_hosts:
        name, _ = naming.pick([("dhcp", _dhcp_hostname(h["mac"]))])
        hosts.append({
            "ip": h["ip"],
            "mac": h["mac"],
            **resolve_vendor_info(h["mac"], h["vendor"], [name]),
            "hostname": name,
            "ports": [],
        })
    return hosts


# ---- profilo associative: scansione dei dispositivi scelti prima di aggiungerli ----
async def run_associative(ip: str, name_hint: str | None = None, batch: Batch | None = None) -> dict:
    """Scansione di un singolo host + riconoscimento adapter. Deve restare
    veloce (vedi compose_nmap_args). name_hint e' il nome gia' trovato dalla
    ricerca iniziale: va preservato, altrimenti si perderebbe (nmap da solo
    raramente trova un hostname su una LAN domestica senza DNS locale)."""
    if batch is None:
        batch = await prepare_batch(flows.ASSOCIATIVE, [ip])
    info = await scan_host(ip, batch)
    adapter, extra = info["adapter"], info["adapter_extra"]
    mac = info["mac"] or extra.get("mac")
    name, name_source = naming.pick([
        ("adapter", extra.get("name") if adapter == "shelly_gen1" else None),
        ("adapter", info.get("api_name")),  # interfaccia locale (Tasmota, ESPHome, Roku, Sonos...)
        ("mdns", name_hint), ("mdns", batch.mdns_names.get(ip)), ("onvif", info.get("onvif_name")),
        ("tls", naming.cn_host(info.get("tls_subject"))), ("web", naming.title_name(info.get("http_title"))),
        ("upnp", info.get("upnp_name")), ("dhcp", _dhcp_hostname(mac)),
        ("netbios", info.get("netbios_name")), ("nmap", info["hostname"]),
    ])
    suggested_name = truncate_name(name) or ip
    suggested_port = scanner._guess_port(info["ports"])
    return {
        "ip": info["ip"],
        "mac": info["mac"] or extra.get("mac"),
        "hostname": info["hostname"],
        "ports": info["ports"],
        "adapter": adapter,
        "suggested_name": suggested_name,
        "name_source": name_source if name else None,
        "suggested_port": suggested_port,
        "shelly_extra": extra.get("extra") if adapter == "shelly_gen1" else None,
        # Dati delle funzioni facoltative (os, titolo, NetBIOS/SNMP, UPnP...).
        "scan_info": scanner.format_scan_info(info),
    }


_running: dict[str, asyncio.Task] = {}


def cancel_associative(ips: list[str] | None = None) -> int:
    """Annulla le ricerche associative in corso (None = tutte). Ritorna quante."""
    n = 0
    for ip, task in list(_running.items()):
        if (ips is None or ip in ips) and not task.done():
            task.cancel()
            n += 1
    return n


def start_associative(ips: list[str], hints: dict) -> list[asyncio.Task]:
    """Avvia la ricerca associativa su piu' IP: i task partono qui (fuori dal
    generatore SSE), cosi' proseguono anche se il browser si disconnette. Le
    funzioni di lotto (mDNS, SSDP) girano una volta sola, condivise."""
    batch_task = asyncio.create_task(prepare_batch(flows.ASSOCIATIVE, ips))

    async def one(ip: str) -> dict:
        return await run_associative(ip, hints.get(ip), await batch_task)

    tasks = []
    for ip in ips:
        task = asyncio.create_task(one(ip))
        _running[ip] = task
        task.add_done_callback(lambda t, ip=ip: _running.pop(ip, None) if _running.get(ip) is t else None)
        tasks.append(task)
    return tasks


# ---- profilo deep: ricerca approfondita ----
async def run_deep(ip: str, batch: Batch, slow: bool = False) -> dict:
    """Scansione approfondita di un host, con i dati di lotto gia' pronti
    (prepare_batch('deep', ips)). Usata dal pulsante e dalla manutenzione notturna."""
    return await scan_host(ip, batch, slow)
