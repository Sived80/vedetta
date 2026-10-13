"""pipeline_probes: moved out of pipeline.py (see tools/split_module.py)."""
from .pipeline_plan import _log_skipped, compose_nmap_args, resolve_plan
import asyncio
from . import discovery, localapi, scanner
from ..applog import logger
from .adapters import shelly_gen1, shelly_gen2


_EMPTY_HOST = {"mac": None, "hostname": None, "ports": [], "http_title": None}


async def _plan_nmap_scan(batch, ip, slow):
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
    return chosen, nmap_args, slow


async def _run_parallel_probes(nmap_args, ip, slow, chosen):
    xml_text, protocol_info, rtsp_info = await _gather_probes(nmap_args, ip, chosen)
    hosts = scanner._parse_hosts(xml_text) if xml_text is not None else []
    info = hosts[0] if hosts else {"ip": ip, **_EMPTY_HOST}
    # The scan timed out: the device is marked as slow for subsequent runs.
    if ip in scanner.timed_out:
        scanner.timed_out.discard(ip)
        info["slow_scan"] = True
        if not info["ports"]:
            await _targeted_ports_fallback(info, ip)
    elif slow:
        info["slow_scan"] = True
    if "service_os" in chosen and nmap_args:
        # the service detection leaves the no-talk ports out: a plain connect still sees them open
        info["ports"] = scanner.with_no_talk_ports(info["ports"], await scanner.no_talk_open_ports(ip))
    return protocol_info, rtsp_info, info


async def _gather_probes(nmap_args, ip, chosen):
    """The nmap scan, the protocol scan (NetBIOS/SNMP) and the RTSP probe, run in parallel: (nmap XML or None, protocol info, RTSP info)."""
    nmap_job = scanner._run_nmap(nmap_args) if nmap_args else None
    proto_job = scanner.protocol_scan(ip) if "netbios_snmp" in chosen else None
    rtsp_job = discovery.rtsp_probe(ip) if "rtsp" in chosen else None
    jobs = [j for j in (nmap_job, proto_job, rtsp_job) if j is not None]
    results = await asyncio.gather(*jobs) if jobs else []
    xml_text = results.pop(0) if nmap_job is not None else None
    protocol_info = results.pop(0) if proto_job is not None else {}
    rtsp_info = results.pop(0) if rtsp_job is not None else {}
    return xml_text, protocol_info, rtsp_info


async def _targeted_ports_fallback(info, ip):
    """The scan timed out and nmap discarded the ports: a targeted scan takes its place."""
    try:
        fast = await scanner.fast_ports(ip)
    except Exception as exc:
        logger.info("%s: scansione mirata di ripiego fallita (%r)", ip, exc)
        fast = None
    if fast and fast.get("ports"):
        info["ports"] = fast["ports"]
        info["http_title"] = info.get("http_title") or fast.get("http_title")
        logger.info("%s: scansione completa scaduta, %d porte trovate con la scansione mirata", ip, len(fast["ports"]))


def _merge_mdns_and_upnp_info(info, ip, protocol_info, chosen, batch):
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
    return meta


def _merge_onvif_rtsp_igmp_info(chosen, ip, rtsp_info, info, meta, batch):
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


async def _read_tls_ssh_and_local_api(chosen, info, ip):
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


async def _confirm_web_identity(chosen, ip, info):
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
    return adapter, extra


async def _probe_shelly_adapter(chosen, info, ip, adapter, extra):
    if "adapter_probe" not in chosen or not any(p["port"] == 80 for p in info["ports"]):
        return adapter, extra
    result = await _shelly_gen1_answer(ip)
    # Only if the response really has the shape of the Shelly API (mac + uptime),
    # otherwise any web server on port 80 would end up classified as Shelly.
    if result.get("mac") and result.get("uptime_seconds") is not None:
        adapter = "shelly_gen1"
        extra = result
        info["battery"] = "yes" if result.get("battery") else "no"
    elif result.get("mac") is None:
        await _shelly_gen2_battery(ip, info)
    return adapter, extra


async def _shelly_gen1_answer(ip) -> dict:
    try:
        return await shelly_gen1.probe(ip, 80)
    except Exception:
        return {}


async def _shelly_gen2_battery(ip, info) -> None:
    """Not a Gen1: maybe a Gen2+ (RPC API), where "devicepower" reveals the battery."""
    try:
        gen2 = await shelly_gen2.battery_probe(ip, 80)
    except Exception:
        gen2 = {}
    if gen2:
        info["battery"] = "yes" if gen2.get("battery") else "no"


def _attach_adapter_result(adapter, extra, info) -> dict:
    info["adapter"] = adapter
    info["adapter_extra"] = extra
    return info
