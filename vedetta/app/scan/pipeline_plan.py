"""pipeline_plan: moved out of pipeline.py (see tools/split_module.py)."""
import asyncio
from dataclasses import dataclass, field
from . import discovery, flows, scanner
from .scan_common import version_exclusion
from ..netutil import get_local_network
from ..applog import logger
from ..storage import settings


# Steps that produce the list of ports (one TCP nmap invocation).
NMAP_PORT_STEPS = ("ports_fast", "ports_all", "service_os")


# Steps that need the ports already found.
NEEDS_PORTS = ("http_title", "adapter_probe", "tls_ssh")


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
        args += ["-sV", "--version-light", *version_exclusion()]
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


# The field of the Batch that each job fills.
_BATCH_FIELD = {"names": "mdns_names", "onvif": "wsd_info", "igmp": "igmp_info", "ssdp": "upnp_info"}


async def prepare_batch(profile: str, ips: list[str], steps: list[str] | None = None) -> Batch:
    """The "batch" part of the profile: mDNS/reverse names and SSDP, once
    for all IPs, in parallel. An error here does not stop the scan: it
    continues without that data."""
    steps = list(steps) if steps is not None else active_steps(profile)
    batch = Batch(steps=steps)
    jobs = _batch_jobs(steps, ips)
    if not jobs:
        return batch
    results = await asyncio.gather(*jobs.values(), return_exceptions=True)
    for key, result in zip(jobs, results):
        if isinstance(result, Exception):
            logger.error("Funzione '%s' fallita: %r", key, result)
            continue
        setattr(batch, _BATCH_FIELD[key], result)
    return batch


def _batch_jobs(steps: list[str], ips: list[str]) -> dict:
    """The LAN-wide jobs of the active steps, by the key of their result."""
    jobs = {}
    if {"mdns", "reverse_names"} & set(steps):
        jobs["names"] = _names_for(steps, ips)
    if "ssdp" in steps:
        jobs["ssdp"] = scanner.ssdp_scan()
    if "onvif" in steps:
        jobs["onvif"] = _wsd()
    if "igmp" in steps:
        jobs["igmp"] = scanner.igmp_scan()
    return jobs


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


async def _wsd() -> dict[str, dict]:
    try:
        _, own_ip = await get_local_network()
    except Exception:
        own_ip = None
    return await discovery.wsd_scan(own_ip)
