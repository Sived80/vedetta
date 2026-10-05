import asyncio
import time

from . import devices_config, dhcp, naming, pipeline, scanner
from .applog import logger
from .history import history
from .state import state


def _port_numbers(ports: list[dict] | None) -> set[int]:
    """Numeri di porta da una lista salvata (le etichette sono "80 · http" o
    solo "18555"). Le porte effimere (49152+) sono escluse: compaiono e
    spariscono a caso e genererebbero avvisi a ogni scansione."""
    numbers = set()
    for p in ports or []:
        head = str(p.get("label", "")).split(" ")[0]
        if head.isdigit() and int(head) < scanner.EPHEMERAL_PORT_START:
            numbers.add(int(head))
    return numbers


def diff_ports(old_ports: list[dict] | None, new_ports: list[dict] | None) -> tuple[list[int], list[int]]:
    """(porte nuove, porte sparite) tra due scansioni successive."""
    old, new = _port_numbers(old_ports), _port_numbers(new_ports)
    return sorted(new - old), sorted(old - new)


FULL_PORTS_EVERY_S = 7 * 86400
_bg_tasks: dict[str, asyncio.Task] = {}
_BG_NMAP_SEM = asyncio.Semaphore(1)   # una sola scansione completa in background alla volta
_FAST_SET = {int(p) for p in scanner.FAST_PORTS.split(",")}


def _merge_ports(old: list[dict] | None, new: list[dict] | None) -> list[dict]:
    """Unione per numero di porta (la voce nuova prevale)."""
    def num(p):
        head = str(p.get("label", "")).split(" ")[0]
        return int(head) if head.isdigit() else None
    merged = {num(p): p for p in old or [] if num(p) is not None}
    merged.update({num(p): p for p in new or [] if num(p) is not None})
    return [merged[k] for k in sorted(merged)]


def schedule_full_ports(device: dict) -> None:
    """Scansione di tutte le porte in BACKGROUND per un dispositivo lento: la ricerca in
    primo piano e' gia' finita con le porte mirate; questa gira dopo, a ritmo cauto (-T3),
    una alla volta, e al termine aggiunge le porte in piu'. Se il servizio si riavvia
    si perde: la prossima ricerca approfondita la rilancia."""
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
        # Seconda fase: servizio e sistema operativo SOLO sulle porte aperte trovate (poche): la
        # scansione completa non li legge, e su un dispositivo lento -sV sull'intero intervallo scade.
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
        info["services_at"] = time.time()   # tentato: non si ripete a ogni ricerca, solo con le porte complete
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
    """Scansione approfondita (profilo deep) di un dispositivo: salva il
    risultato (con data e storico), confronta le porte con la scansione
    precedente e aggiorna la pagina. Usata sia dal pulsante sia dalla
    manutenzione notturna. batch = pipeline.prepare_batch("deep", ips)."""
    ip = device["ip"]
    label = f"{ip} ({device.get('name') or ip})"
    started = time.monotonic()
    slow = bool((device.get("scan_info") or {}).get("slow_scan"))
    info = await pipeline.run_deep(ip, batch, slow)
    fields = scanner.format_scan_info(info)
    elapsed = time.monotonic() - started

    if not fields:
        # Non si sovrascrive una scansione vecchia ma buona con un risultato
        # vuoto (host momentaneamente irraggiungibile o troppo filtrato).
        logger.warning("%s scansione completata senza alcun risultato utile (%.0fs), dati precedenti mantenuti", label, elapsed)
        return {}

    previous = device.get("scan_info") or {}
    now = time.time()
    fields["scanned_at"] = now
    if info.get("slow_scan"):
        # Dispositivo lento: la scansione in primo piano copre solo le porte mirate. Le porte
        # fuori da quell'elenco (trovate dalla scansione completa in background) si tengono.
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
    # Dispositivo lento: la scansione completa delle porte prosegue in background.
    if info.get("slow_scan") and (now - float(previous.get("full_ports_at") or 0) > FULL_PORTS_EVERY_S
                                  or not previous.get("services_at")):
        schedule_full_ports(device)
    return fields
