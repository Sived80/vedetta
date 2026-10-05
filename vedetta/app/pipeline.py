"""Single search flow: independent functions (steps) enabled by profiles.

Registry and defaults in flows.py, user choices in settings.json (key
"flows"), read on every run: changing a setting takes effect from the next
scan, without a restart.

Function -> primitive map in scanner.py:
  arp            scanner.arp_scan             host discovery (initial profile only)
  mdns           scanner.mdns_scan            passive Bonjour/Avahi names
  reverse_names  scanner.resolve_mdns_name    avahi reverse resolution, for IPs without a name
  ssdp           scanner.ssdp_scan            UPnP (once for the whole batch)
  netbios_snmp   scanner.protocol_scan        NetBIOS/SNMP (light nmap -sU)
  ports_fast     (nmap flag)                  -p- with host-timeout 30s
  ports_all      (nmap flag)                  -p- with host-timeout 150s
  service_os     (nmap flag)                  -sV --version-light
  http_title     (nmap flag + direct GET)     --script http-title (with service_os) and
                                              HTTP confirmation of ports (_confirm_http_ports)
  adapter_probe  adapter shelly_gen1.probe    Shelly detection on port 80

Steps that are flags of the same nmap are composed into ONE single invocation
(compose_nmap_args). A step that depends on the output of another (http_title and
adapter_probe need the ports) is skipped with an INFO log, without errors,
when the dependency is missing."""
import asyncio
import time
from dataclasses import dataclass, field

from . import dhcp, discovery, flows, localapi, naming, scanner, settings
from .adapters import shelly_gen1, shelly_gen2
from .applog import logger
from .formatters import truncate_name
from .netutil import get_local_network
from .vendor_lookup import resolve_vendor_info

# Steps that produce the list of ports (one TCP nmap invocation).
NMAP_PORT_STEPS = ("ports_fast", "ports_all", "service_os")
# Steps that need the ports already found.
NEEDS_PORTS = ("http_title", "adapter_probe", "tls_ssh")

_EMPTY_HOST = {"mac": None, "hostname": None, "ports": [], "http_title": None}


def active_steps(profile: str) -> list[str]:
    """Active steps of the profile, re-read from the settings on every call."""
    return settings.flows_load()[profile]


def compose_nmap_args(steps, ip: str, slow: bool = False) -> list[str] | None:
    """ONE single nmap invocation for the active steps, or None if no step
    requires one (no TCP scan).

    With all steps it yields exactly the old deep scan
    (-T4 -sV --version-light --host-timeout 150s --script http-title -p-),
    with ports_fast alone the old quick scan (-T4 -p- --host-timeout 30s).
    -T4 is the speed nmap recommends for reliable LANs; -sV without
    --version-light can take almost 100s on a single difficult port
    (verified), and without -sV the -p- scan costs as much as a fixed list,
    so -p- is always used and never --top-ports (which would exclude
    homelab ports such as 8006/Proxmox or 8123/Home Assistant). The timeout is long (150s)
    if there is a heavy scan (ports_all/service_os), short (30s) for
    quick detection only. --script http-title travels together with service_os
    (as in the old deep scan): on its own on the quick ports it
    would cost time that the associative search never spent."""
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
        # Slow device (the all-ports scan timed out in the past): targeted ports
        # and reduced maximum time, instead of sitting in the queue for minutes.
        args[args.index("-p-"):args.index("-p-") + 1] = ["-p", scanner.FAST_PORTS]
        args[args.index("--host-timeout") + 1] = "60s"
    args.append(ip)
    return args


def resolve_plan(steps) -> tuple[list[str], list[tuple[str, str]]]:
    """(runnable steps, [(skipped step, reason)]): skips whatever depends on an
    output that no active step produces."""
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
    """Results shared by a batch of devices (computed only once:
    mDNS and SSDP are LAN-wide broadcasts, not per single host)."""
    steps: list[str]
    mdns_names: dict[str, str] = field(default_factory=dict)
    upnp_info: dict[str, dict] = field(default_factory=dict)
    wsd_info: dict[str, dict] = field(default_factory=dict)
    igmp_info: dict[str, list] = field(default_factory=dict)


async def _names_for(steps, ips: list[str]) -> dict[str, str]:
    """Names from mdns (passive, one call for the whole network) and/or reverse_names
    (targeted active query on the IPs left without a name)."""
    chosen = set(steps)
    if "mdns" in chosen and "reverse_names" in chosen:
        return await scanner.resolve_names(ips)
    if "mdns" in chosen:
        return await scanner.mdns_scan()
    if "reverse_names" in chosen:
        return await scanner.resolve_names(ips, passive_names={})
    return {}


async def prepare_batch(profile: str, ips: list[str], steps: list[str] | None = None) -> Batch:
    """The "batch" part of the profile: mDNS/reverse names and SSDP, once
    for all IPs, in parallel. An error here does not stop the scan: it
    continues without that data."""
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
    """The profile's "per host" functions (composed nmap, NetBIOS/SNMP, web
    port confirmation, adapter) merged with the batch data. Returns the same dict that
    full_scan produced (plus the 'adapter'/'adapter_extra' keys)."""
    steps = batch.steps
    run, skipped = resolve_plan(steps)
    _log_skipped(skipped, ip)
    chosen = set(run)

    # The TCP nmap and the UDP nmap (NetBIOS/SNMP) are separate processes launched in
    # parallel, not one after the other: they do not add to the already long times of -p- -sV.
    nmap_args = compose_nmap_args(run, ip, slow)
    # First we measure whether the device can handle the all-ports scan (pilot test
    # on 1000): if it is slow we switch straight to targeted ports, without waiting for the 150 s.
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
    # The scan timed out and nmap discarded the ports: fallback targeted scan, and
    # the device is marked as slow for subsequent runs.
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
    # Model/manufacturer announced via mDNS TXT (_device-info, AirPlay, Chromecast...).
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

    # ONVIF/WS-Discovery self-declaration and RTSP Server header.
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
    # TLS certificate and SSH key: a second light nmap only on the ports already found
    # open (inside the -p- scan the scripts stretched it beyond its timeout).
    if "tls_ssh" in chosen and info["ports"]:
        try:
            info.update(await scanner.tls_ssh_scan(ip, info["ports"]))
        except Exception as exc:
            logger.info("%s: certificato/chiave non letti (%r)", ip, exc)
    if "local_api" in chosen:
        # Without known ports (slow devices that exceed the nmap timeout) port 80 is
        # tried anyway: it is a single documented GET, with a short timeout.
        try:
            info.update(await localapi.probe(ip, [p["port"] for p in info["ports"]] or [80]))
        except Exception as exc:
            logger.info("%s: interfaccia locale non letta (%r)", ip, exc)

    if "http_title" in chosen:
        await scanner._confirm_http_ports(ip, info["ports"])
        # Server and title found by the GET: they help recognize what it is
        # (nmap's title, if present, takes precedence).
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
        # Only if the response really has the shape of the Shelly API (mac + uptime),
        # otherwise any web server on port 80 would end up classified as Shelly.
        if result.get("mac") and result.get("uptime_seconds") is not None:
            adapter = "shelly_gen1"
            extra = result
            info["battery"] = "yes" if result.get("battery") else "no"
        elif result.get("mac") is None:
            # Not a Gen1: maybe a Gen2+ (RPC API), where "devicepower" reveals the battery.
            try:
                gen2 = await shelly_gen2.battery_probe(ip, 80)
            except Exception:
                gen2 = {}
            if gen2:
                info["battery"] = "yes" if gen2.get("battery") else "no"
    info["adapter"] = adapter
    info["adapter_extra"] = extra
    return info


# ---- initial profile: initial search ----
def _dhcp_hostname(mac: str | None) -> str | None:
    return (dhcp.seen.get((mac or "").lower()) or {}).get("hostname")


async def run_initial() -> list[dict]:
    """Host discovery: ARP only, hence IP and MAC (and the MAC vendor). No name
    search: the only name that gets through is the DHCP one already heard, kept as an internal
    hint for the analysis that starts on adding (it is not shown)."""
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


# ---- associative profile: scan of the chosen devices before adding them ----
async def run_associative(ip: str, name_hint: str | None = None, batch: Batch | None = None) -> dict:
    """Scan of a single host + adapter detection. It must stay
    fast (see compose_nmap_args). name_hint is the name already found by the
    initial search: it must be preserved, otherwise it would be lost (nmap alone
    rarely finds a hostname on a home LAN without local DNS)."""
    if batch is None:
        batch = await prepare_batch(flows.ASSOCIATIVE, [ip])
    info = await scan_host(ip, batch)
    adapter, extra = info["adapter"], info["adapter_extra"]
    mac = info["mac"] or extra.get("mac")
    name, name_source = naming.pick([
        ("adapter", extra.get("name") if adapter == "shelly_gen1" else None),
        ("adapter", info.get("api_name")),  # local interface (Tasmota, ESPHome, Roku, Sonos...)
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
        # Data from the optional functions (os, title, NetBIOS/SNMP, UPnP...).
        "scan_info": scanner.format_scan_info(info),
    }


_running: dict[str, asyncio.Task] = {}


def cancel_associative(ips: list[str] | None = None) -> int:
    """Cancel the associative searches in progress (None = all). Returns how many."""
    n = 0
    for ip, task in list(_running.items()):
        if (ips is None or ip in ips) and not task.done():
            task.cancel()
            n += 1
    return n


def start_associative(ips: list[str], hints: dict) -> list[asyncio.Task]:
    """Start the associative search on several IPs: the tasks start here (outside the
    SSE generator), so they carry on even if the browser disconnects. The
    batch functions (mDNS, SSDP) run only once, shared."""
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


# ---- deep profile: deep search ----
async def run_deep(ip: str, batch: Batch, slow: bool = False) -> dict:
    """Deep scan of a host, with the batch data already ready
    (prepare_batch('deep', ips)). Used by the button and by nightly maintenance."""
    return await scan_host(ip, batch, slow)
