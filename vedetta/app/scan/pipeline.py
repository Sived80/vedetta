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

from . import dhcp, flows, scanner
from ..recognition import naming
from .adapters import shelly_gen1
from ..applog import logger
from ..formatters import truncate_name
from ..netutil import get_local_network
from ..recognition.vendor_lookup import resolve_vendor_info
from .pipeline_plan import Batch, NEEDS_PORTS, NMAP_PORT_STEPS, _log_skipped, _names_for, _wsd, active_steps, compose_nmap_args, prepare_batch, resolve_plan  # noqa: F401
from .pipeline_probes import _EMPTY_HOST, _attach_adapter_result, _confirm_web_identity, _merge_mdns_and_upnp_info, _merge_onvif_rtsp_igmp_info, _plan_nmap_scan, _probe_shelly_adapter, _read_tls_ssh_and_local_api, _run_parallel_probes  # noqa: F401


async def scan_host(ip: str, batch: Batch, slow: bool = False) -> dict:
    """The profile's "per host" functions (composed nmap, NetBIOS/SNMP, web
    port confirmation, adapter) merged with the batch data. Returns the same dict that
    full_scan produced (plus the 'adapter'/'adapter_extra' keys)."""
    chosen, nmap_args, slow = await _plan_nmap_scan(batch, ip, slow)
    protocol_info, rtsp_info, info = await _run_parallel_probes(nmap_args, ip, slow, chosen)
    meta = _merge_mdns_and_upnp_info(info, ip, protocol_info, chosen, batch)
    _merge_onvif_rtsp_igmp_info(chosen, ip, rtsp_info, info, meta, batch)
    await _read_tls_ssh_and_local_api(chosen, info, ip)
    adapter, extra = await _confirm_web_identity(chosen, ip, info)
    adapter, extra = await _probe_shelly_adapter(chosen, info, ip, adapter, extra)
    return _attach_adapter_result(adapter, extra, info)


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
