"""The full port scan of a slow device, in the BACKGROUND (schedule_full_ports): the deep search (rescan.py) covers only the targeted ports of such a device;
this one runs afterwards, at a cautious pace and one at a time, adds the extra ports and reads their services. Moved out of rescan.py: it changes for other reasons than the deep search."""
import asyncio
import time

from ..storage import devices_config
from . import full_ports_plan, host_load, scanner, touch_policy
from .scan_common import is_no_talk_port, port_number
from ..applog import logger
from ..state import state
from ..storage import journal


def port_numbers(ports: list[dict] | None) -> set[int]:
    """Port numbers from a saved list (the labels are "80 · http" or
    just "18555"). Ephemeral ports (49152+) are excluded: they appear and
    disappear at random and would generate alerts on every scan."""
    numbers = set()
    for p in ports or []:
        number = port_number(p)
        if number is not None and number < scanner.EPHEMERAL_PORT_START:
            numbers.add(number)
    return numbers


FULL_PORTS_EVERY_S = 7 * 86400
_bg_tasks: dict[str, asyncio.Task] = {}
_BG_NMAP_SEM = asyncio.Semaphore(1)   # only one full background scan at a time
FAST_SET = {int(p) for p in scanner.FAST_PORTS.split(",")}


def merge_ports(old: list[dict] | None, new: list[dict] | None) -> list[dict]:
    """Union by port number (the new entry wins)."""
    merged = {port_number(p): p for p in old or [] if port_number(p) is not None}
    merged.update({port_number(p): p for p in new or [] if port_number(p) is not None})
    return [merged[k] for k in sorted(merged)]


def schedule_full_ports(device: dict) -> None:
    """Scan of all the ports in the BACKGROUND for a slow device: the foreground search
    has already finished with the targeted ports; this one runs afterwards, at a cautious pace (-T3),
    one at a time, and when done adds the extra ports. If the service restarts
    it is lost: the next deep search relaunches it."""
    ip = device["ip"]
    if not touch_policy.may_touch(device) or (ip in _bg_tasks and not _bg_tasks[ip].done()):
        return
    _bg_tasks[ip] = asyncio.create_task(_full_ports_background(device["id"], ip))


async def _full_ports_background(device_id: str, ip: str) -> None:
    try:
        await _scan_all_ports(device_id, ip)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("%s: scansione completa in background fallita", ip)


def _may_be_scanned(device_id: str) -> bool:
    """The card is still there and may be touched: the scan waited for its turn, and the user may have said «don't touch» meanwhile."""
    waiting = next((d for d in devices_config.load_devices() if d["id"] == device_id), None)
    return waiting is not None and touch_policy.may_touch(waiting)


def _card(device_id: str) -> dict | None:
    return next((d for d in devices_config.load_devices() if d["id"] == device_id), None)


async def _scan_all_ports(device_id: str, ip: str) -> None:
    """The full scan by blocks of ports: each block has its own limit, what it finds is saved at once and the card remembers the next block, so a slow device never loses a whole run to one timeout. A run stops after
    a few blocks (the next deep search goes on) and at the first block that times out (it is not repeated for a day, then two, four, seven)."""
    for done in range(full_ports_plan.BLOCKS_PER_RUN):
        if not _may_be_scanned(device_id):
            return
        if pressure := host_load.busy():
            host_load.note_deferred(pressure)
            logger.info("%s: scansione completa rimandata, il sistema e' sotto pressione (%s)", ip, pressure)
            return
        first, last = full_ports_plan.block(int((_card(device_id).get("scan_info") or {}).get("full_ports_next") or 1))
        hosts = await _background_nmap(ip, ["-T3", "-p", f"{first}-{last}", "--host-timeout", f"{full_ports_plan.BLOCK_TIMEOUT_S}s", ip])
        if ip in scanner.timed_out:
            scanner.timed_out.discard(ip)
            _note_block_timed_out(device_id, ip, first, last)
            return
        if await _save_block(device_id, ip, last, _ports_found(hosts)):
            return
        if done + 1 < full_ports_plan.BLOCKS_PER_RUN:
            await asyncio.sleep(full_ports_plan.PAUSE_S)


def _note_block_timed_out(device_id: str, ip: str, first: int, last: int) -> None:
    """The block stays the next one; the card waits before the scan is tried again."""
    current = _card(device_id)
    if not current:
        return
    info = dict(current.get("scan_info") or {})
    failures = int(info.get("full_ports_failures") or 0) + 1
    delay = full_ports_plan.retry_delay(failures)
    info.update(full_ports_next=first, full_ports_failures=failures, full_ports_retry_at=time.time() + delay)
    devices_config.update_scan_info(device_id, info)
    logger.info("%s: porte %d-%d: scansione in background scaduta, restano le porte lette; si riprova tra %d ore", ip, first, last, delay // 3600)
    journal.add("detail", "journal.fullports_failed", icon="alert", ip=ip)


async def _save_block(device_id: str, ip: str, last: int, found: list[dict]) -> bool:
    """The ports of a block joined to the card as it is NOW (it may have changed while nmap ran); the next block remembered. True when there is nothing more to scan: the last block was done (the services are read, the
    page and the journal told) or the card is gone."""
    current = _card(device_id)
    if not current:
        return True
    info = dict(current.get("scan_info") or {})
    info.setdefault("full_ports_base", len(info.get("ports") or []))
    info["ports"] = merge_ports(info.get("ports"), found)
    for key in ("full_ports_failures", "full_ports_retry_at"):
        info.pop(key, None)
    if last < full_ports_plan.LAST_PORT:
        info["full_ports_next"] = last + 1
        devices_config.update_scan_info(device_id, info)
        logger.info("%s: porte fino alla %d lette in background, %d porte aperte finora", ip, last, len(info["ports"]))
        return False
    info["full_ports_at"] = time.time()
    await _read_services(info, ip)
    added = len(info["ports"]) - int(info.pop("full_ports_base"))
    info.pop("full_ports_next", None)
    devices_config.update_scan_info(device_id, info)
    await state.refresh_device(device_id, force=True)
    logger.info("%s: scansione completa in background terminata, %d porte (%+d)", ip, len(info["ports"]), added)
    journal.add("detail", "journal.fullports", icon="magnify", ip=ip, ports=len(info["ports"]), added=max(added, 0))
    return True


async def _read_services(info: dict, ip: str) -> None:
    """Second phase: service and operating system ONLY on the open ports found (few): the
    full scan does not read them, and on a slow device -sV over the whole range times out."""
    try:
        open_nums = [str(n) for n in sorted(port_numbers([p for p in info["ports"] if not is_no_talk_port(p)]))][:40]
        if open_nums:
            svc_hosts = await _background_nmap(ip, ["-T3", "-sV", "--version-light", "-p", ",".join(open_nums), "--host-timeout", "300s", ip])
            if ip in scanner.timed_out:
                scanner.timed_out.discard(ip)
            elif svc_hosts:
                info["ports"] = merge_ports(info["ports"], _ports_found(svc_hosts))
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("%s: riconoscimento dei servizi in background fallito", ip)
    info["services_at"] = time.time()   # attempted: not repeated on every search, only with the full ports


async def _background_nmap(ip: str, args: list[str]) -> list[dict]:
    """One nmap run of the background scan (one at a time, whatever the device) and the hosts of its answer."""
    return scanner._parse_hosts(await scanner._run_nmap(args, semaphore=_BG_NMAP_SEM))


def _ports_found(hosts: list[dict]) -> list[dict]:
    return scanner.format_scan_info({"ports": hosts[0]["ports"]}).get("ports", []) if hosts else []
