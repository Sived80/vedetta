"""Deep search of one device (rescan_device): runs the deep profile, saves the result and its history, compares the open ports with the previous scan and warns about the ones
that changed, applies a better name, and for a slow device schedules the full port scan in the background (rescan_background.py)."""
import asyncio
import time

from ..storage import devices_config
from . import dhcp, pipeline, scanner, touch_policy
from .rescan_background import FAST_SET, FULL_PORTS_EVERY_S, merge_ports, port_numbers, schedule_full_ports
from .scan_common import port_number
from ..recognition import naming
from ..applog import logger
from ..storage.history import history
from ..state import state


CHURN_BAND_START = 32768   # the default dynamic range of Linux (32768-60999), which a TV, a phone or a repeater uses for the ports it listens on


def _all_numbers(ports: list[dict] | None) -> set[int]:
    return {n for p in ports or [] if (n := port_number(p)) is not None}


def diff_ports(old_ports: list[dict] | None, new_ports: list[dict] | None) -> tuple[list[int], list[int]]:
    """(new ports, vanished ports) between two consecutive scans. When the ports of the high band (CHURN_BAND_START and up) change in BOTH directions the device is only shuffling its
    dynamic ports, so none of the high ones is reported; one direction only (a service that appears or goes) and everything below the band are reported as before."""
    old, new = port_numbers(old_ports), port_numbers(new_ports)
    opened, closed = sorted(new - old), sorted(old - new)
    all_old, all_new = _all_numbers(old_ports), _all_numbers(new_ports)
    if any(p >= CHURN_BAND_START for p in all_new - all_old) and any(p >= CHURN_BAND_START for p in all_old - all_new):
        opened, closed = [p for p in opened if p < CHURN_BAND_START], [p for p in closed if p < CHURN_BAND_START]
    return opened, closed


# Clues a device announces by itself (multicast / broadcast). A sleeping phone often stays silent during a scan.
_ANNOUNCED_CLUES = ("mdns_name", "mdns_model", "mdns_manufacturer", "mdns_services", "upnp_name", "upnp_manufacturer",
                    "upnp_model", "netbios_name", "wsd_types", "igmp_groups")
# Clues read from an open port: they only make sense while the port answers.
_WEB_CLUES = ("http_title", "http_server")
_PORT_CLUES = ("http_title", "http_server", "rtsp_server", "tls_subject", "tls_issuer", "ssh_hostkey", "snmp_descr",
               "onvif_name", "onvif_hardware", "onvif_manufacturer", "api_source", "api_vendor", "api_model",
               "api_name", "api_fw", "battery")


async def rescan_device(device: dict, batch: pipeline.Batch) -> dict:
    """Deep scan (deep profile) of a device: saves the
    result (with date and history), compares the ports with the previous
    scan and updates the page. Used both by the button and by the
    nightly maintenance. batch = pipeline.prepare_batch("deep", ips)."""
    if not touch_policy.may_touch(device):
        return {}   # only watching: nothing is sent to it
    _result, label, info, fields, elapsed = await _run_deep_scan(device, batch)
    if _result is not None:
        return _result
    previous, now = _keep_ports_of_slow_device(fields, info, device)
    await _save_scan_and_alert_ports(previous, fields, device, now, label)
    name, source = _pick_name_from_scan(info, device)
    return await _apply_name_and_refresh(fields, name, label, elapsed, device, source, info, now, previous)


async def _run_deep_scan(device, batch):
    ip = device["ip"]
    label = f"{ip} ({device.get('name') or ip})"
    started = time.monotonic()
    slow = bool((device.get("scan_info") or {}).get("slow_scan"))
    if touch_policy.touch_level(device) == touch_policy.CALM:
        batch = touch_policy.calm_batch(batch)
    info = await pipeline.run_deep(ip, batch, slow)
    fields = scanner.format_scan_info(info)
    elapsed = time.monotonic() - started

    if not fields:
        # An old but good scan is not overwritten with an empty result
        # (host momentarily unreachable or too filtered).
        logger.warning("%s scansione completata senza alcun risultato utile (%.0fs), dati precedenti mantenuti", label, elapsed)
        # Remember that the deep search was done, without touching scanned_at (that one means "ports and services
        # were really read" and feeds the mobile guess): otherwise a device that never answers (a phone with every
        # port closed) would stay "never analysed" forever and be retried by every "only missing" search and night.
        kept = dict(device.get("scan_info") or {})
        kept["deep_empty_at"] = time.time()
        devices_config.update_scan_info(device["id"], kept)
        return ({}), None, None, None, None
    return None, label, info, fields, elapsed


def _keep_ports_of_slow_device(fields, info, device):
    previous = device.get("scan_info") or {}
    now = time.time()
    fields["scanned_at"] = now
    if info.get("slow_scan"):
        # Slow device: the foreground scan only covers the targeted ports. The ports
        # outside that list (found by the full background scan) are kept.
        keep = [p for p in previous.get("ports") or [] if port_number(p) not in (None, *FAST_SET)]
        if keep:
            fields["ports"] = merge_ports(keep, fields.get("ports"))
        if previous.get("full_ports_at"):
            fields["full_ports_at"] = previous["full_ports_at"]
        if previous.get("services_at"):
            fields["services_at"] = previous["services_at"]
    return previous, now


async def _save_scan_and_alert_ports(previous, fields, device, now, label):
    _keep_previous_clues(previous, fields)
    _keep_analysis_ports(previous, fields)
    devices_config.update_scan_info(device["id"], fields)
    await asyncio.to_thread(history.save_scan, device["id"], now, fields)

    if previous:
        opened, closed = diff_ports(previous.get("ports"), fields.get("ports"))
        if not previous.get("scanned_at"):
            closed = []   # the ports kept from the analysis are a start, not a deep reading: a port that this search did not see is no proof that it closed
        if opened:
            ports = ", ".join(map(str, opened))
            state.emit_alert(f"{label}: nuova porta aperta {ports}", "alert.port_opened", label=label, ports=ports)
        if closed:
            ports = ", ".join(map(str, closed))
            state.emit_alert(f"{label}: porta non piu' aperta {ports}", "alert.port_closed", label=label, ports=ports)


def _keep_analysis_ports(previous: dict, fields: dict) -> None:
    """The ports that only the analysis saw (the card has no `scanned_at` yet) stay when this deep search found none: a device that stalls under the long scan (a TV, a recorder) must not lose them.
    After a deep search had read ports, an empty result is a real change and the list goes."""
    if previous.get("ports") and not previous.get("scanned_at") and not fields.get("ports"):
        fields["ports"] = previous["ports"]


def _keep_previous_clues(previous: dict, fields: dict) -> None:
    """A deep scan replaces the saved data, so what it did not hear this time would be lost and the device could fall
    back to "Other devices" (an iPhone that was asleep: no Bonjour name or model). Announced clues are kept when the
    new scan lacks them. A clue read from a port is kept when the port is still open: a read that did not happen (the
    answer came late, the network was busy) must not erase a title that was read before; if the scan found no open
    port at all (device asleep, off or filtered) every old clue stays, because nothing in the new result contradicts it.
    The page of a device whose web port is gone loses its title, and the other port clues go with their ports."""
    for key in _ANNOUNCED_CLUES + _PORT_CLUES:
        if key not in fields and previous.get(key) and (key in _ANNOUNCED_CLUES or _port_still_there(key, previous, fields)):
            fields[key] = previous[key]


def _port_still_there(key: str, previous: dict, fields: dict) -> bool:
    """May a clue read from a port be kept? Yes if the scan found no open port, or if a port that could have given it is still open (for the web clues: a web port)."""
    if not fields.get("ports"):
        return True
    before = [p for p in previous.get("ports") or [] if p.get("web_ui")] if key in _WEB_CLUES else previous.get("ports")
    return bool(port_numbers(before) & port_numbers(fields["ports"]))


def _pick_name_from_scan(info, device):
    extra = info.get("adapter_extra") or {}
    mac = info.get("mac") or extra.get("mac") or state._last_mac.get(device["id"])
    name, source = naming.pick([
        ("adapter", extra.get("name") if info.get("adapter") == "shelly_gen1" else None),
        ("adapter", info.get("api_name")), ("onvif", info.get("onvif_name")),
        ("tls", naming.cn_host(info.get("tls_subject"))), ("web", naming.title_name(info.get("http_title"))),
        ("mdns", info.get("mdns_name")), ("upnp", info.get("upnp_name")),
        ("dhcp", ((dhcp.seen.get((mac or "").lower())) or {}).get("hostname")),
        ("netbios", info.get("netbios_name")), ("nmap", info.get("hostname")),
    ])
    return name, source


async def _apply_name_and_refresh(fields, name, label, elapsed, device, source, info, now, previous) -> dict:
    if name and naming.is_better(device, source, name):
        if await asyncio.to_thread(devices_config.update_auto_name, device["id"], name, source):
            logger.info("%s nome aggiornato: \"%s\" (%s)", label, name, source)

    logger.info("%s scansionato in %.0fs", label, elapsed)
    await state.refresh_device(device["id"], force=True)
    # Slow device: the full port scan continues in the background.
    if info.get("slow_scan") and (now - float(previous.get("full_ports_at") or 0) > FULL_PORTS_EVERY_S
                                  or not previous.get("services_at")):
        schedule_full_ports(device)
    return fields
