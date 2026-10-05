import asyncio
import time

from . import devices_config, dhcp, naming, pipeline, scanner
from .applog import logger
from .history import history
from .state import state


def _port_numbers(ports: list[dict] | None) -> set[int]:
    """Port numbers from a saved list (the labels are "80 · http" or
    just "18555"). Ephemeral ports (49152+) are excluded: they appear and
    disappear at random and would generate alerts on every scan."""
    numbers = set()
    for p in ports or []:
        head = str(p.get("label", "")).split(" ")[0]
        if head.isdigit() and int(head) < scanner.EPHEMERAL_PORT_START:
            numbers.add(int(head))
    return numbers


def diff_ports(old_ports: list[dict] | None, new_ports: list[dict] | None) -> tuple[list[int], list[int]]:
    """(new ports, vanished ports) between two consecutive scans."""
    old, new = _port_numbers(old_ports), _port_numbers(new_ports)
    return sorted(new - old), sorted(old - new)


FULL_PORTS_EVERY_S = 7 * 86400
_bg_tasks: dict[str, asyncio.Task] = {}
_BG_NMAP_SEM = asyncio.Semaphore(1)   # only one full background scan at a time
_FAST_SET = {int(p) for p in scanner.FAST_PORTS.split(",")}


def _merge_ports(old: list[dict] | None, new: list[dict] | None) -> list[dict]:
    """Union by port number (the new entry wins)."""
    def num(p):
        head = str(p.get("label", "")).split(" ")[0]
        return int(head) if head.isdigit() else None
    merged = {num(p): p for p in old or [] if num(p) is not None}
    merged.update({num(p): p for p in new or [] if num(p) is not None})
    return [merged[k] for k in sorted(merged)]


def schedule_full_ports(device: dict) -> None:
    """Scan of all the ports in the BACKGROUND for a slow device: the foreground search
    has already finished with the targeted ports; this one runs afterwards, at a cautious pace (-T3),
    one at a time, and when done adds the extra ports. If the service restarts
    it is lost: the next deep search relaunches it."""
    ip = device["ip"]
    if ip in _bg_tasks and not _bg_tasks[ip].done():
        return
    _bg_tasks[ip] = asyncio.create_task(_full_ports_background(device["id"], ip))


async def _full_ports_background(device_id: str, ip: str) -> None:
    from . import journal
    try:
        xml_text = await scanner._run_nmap(["-T3", "-p-", "--host-timeout", "900s", ip], semaphore=_BG_NMAP_SEM)
        hosts = scanner._parse_hosts(xml_text)
        if ip in scanner.timed_out:
            scanner.timed_out.discard(ip)
            logger.info("%s: scansione completa in background scaduta, restano le porte mirate", ip)
            journal.add("detail", "journal.fullports_failed", icon="alert", ip=ip)
            return
        found = scanner.format_scan_info({"ports": hosts[0]["ports"]}).get("ports", []) if hosts else []
        current = next((d for d in devices_config.load_devices() if d["id"] == device_id), None)
        if not current:
            return
        info = dict(current.get("scan_info") or {})
        before = len(info.get("ports") or [])
        info["ports"] = _merge_ports(info.get("ports"), found)
        info["full_ports_at"] = time.time()
        # Second phase: service and operating system ONLY on the open ports found (few): the
        # full scan does not read them, and on a slow device -sV over the whole range times out.
        try:
            open_nums = [str(n) for n in sorted(_port_numbers(info["ports"]))][:40]
            if open_nums:
                xml_text = await scanner._run_nmap(["-T3", "-sV", "--version-light", "-p", ",".join(open_nums),
                                                     "--host-timeout", "300s", ip], semaphore=_BG_NMAP_SEM)
                svc_hosts = scanner._parse_hosts(xml_text)
                if ip in scanner.timed_out:
                    scanner.timed_out.discard(ip)
                elif svc_hosts:
                    svc = scanner.format_scan_info({"ports": svc_hosts[0]["ports"]}).get("ports", [])
                    info["ports"] = _merge_ports(info["ports"], svc)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("%s: riconoscimento dei servizi in background fallito", ip)
        info["services_at"] = time.time()   # attempted: not repeated on every search, only with the full ports
        devices_config.update_scan_info(device_id, info)
        await state.refresh_device(device_id, force=True)
        added = len(info["ports"]) - before
        logger.info("%s: scansione completa in background terminata, %d porte (%+d)", ip, len(info["ports"]), added)
        journal.add("detail", "journal.fullports", icon="magnify", ip=ip, ports=len(info["ports"]), added=max(added, 0))
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("%s: scansione completa in background fallita", ip)


async def rescan_device(device: dict, batch: pipeline.Batch) -> dict:
    """Deep scan (deep profile) of a device: saves the
    result (with date and history), compares the ports with the previous
    scan and updates the page. Used both by the button and by the
    nightly maintenance. batch = pipeline.prepare_batch("deep", ips)."""
    ip = device["ip"]
    label = f"{ip} ({device.get('name') or ip})"
    started = time.monotonic()
    slow = bool((device.get("scan_info") or {}).get("slow_scan"))
    info = await pipeline.run_deep(ip, batch, slow)
    fields = scanner.format_scan_info(info)
    elapsed = time.monotonic() - started

    if not fields:
        # An old but good scan is not overwritten with an empty result
        # (host momentarily unreachable or too filtered).
        logger.warning("%s scansione completata senza alcun risultato utile (%.0fs), dati precedenti mantenuti", label, elapsed)
        return {}

    previous = device.get("scan_info") or {}
    now = time.time()
    fields["scanned_at"] = now
    if info.get("slow_scan"):
        # Slow device: the foreground scan only covers the targeted ports. The ports
        # outside that list (found by the full background scan) are kept.
        keep = [p for p in previous.get("ports") or []
                if str(p.get("label", "")).split(" ")[0].isdigit() and int(str(p["label"]).split(" ")[0]) not in _FAST_SET]
        if keep:
            fields["ports"] = _merge_ports(keep, fields.get("ports"))
        if previous.get("full_ports_at"):
            fields["full_ports_at"] = previous["full_ports_at"]
        if previous.get("services_at"):
            fields["services_at"] = previous["services_at"]
    devices_config.update_scan_info(device["id"], fields)
    await asyncio.to_thread(history.save_scan, device["id"], now, fields)

    if previous:
        opened, closed = diff_ports(previous.get("ports"), fields.get("ports"))
        if opened:
            ports = ", ".join(map(str, opened))
            state.emit_alert(f"{label}: nuova porta aperta {ports}", "alert.port_opened", label=label, ports=ports)
        if closed:
            ports = ", ".join(map(str, closed))
            state.emit_alert(f"{label}: porta non piu' aperta {ports}", "alert.port_closed", label=label, ports=ports)

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
    if name and naming.is_better(device, source):
        if await asyncio.to_thread(devices_config.update_auto_name, device["id"], name, source):
            logger.info("%s nome aggiornato: \"%s\" (%s)", label, name, source)

    logger.info("%s scansionato in %.0fs", label, elapsed)
    await state.refresh_device(device["id"], force=True)
    # Slow device: the full port scan continues in the background.
    if info.get("slow_scan") and (now - float(previous.get("full_ports_at") or 0) > FULL_PORTS_EVERY_S
                                  or not previous.get("services_at")):
        schedule_full_ports(device)
    return fields
