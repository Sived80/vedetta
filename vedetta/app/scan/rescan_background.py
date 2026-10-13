"""The full port scan of a slow device, in the BACKGROUND (schedule_full_ports): the deep search (rescan.py) covers only the targeted ports of such a device;
this one runs afterwards, at a cautious pace and one at a time, adds the extra ports and reads their services. Moved out of rescan.py: it changes for other reasons than the deep search."""
import asyncio
import time

from ..storage import devices_config
from . import scanner, touch_policy
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


async def _scan_all_ports(device_id: str, ip: str) -> None:
    if not _may_be_scanned(device_id):
        return
    hosts = await _background_nmap(ip, ["-T3", "-p-", "--host-timeout", "900s", ip])
    if ip in scanner.timed_out:
        scanner.timed_out.discard(ip)
        logger.info("%s: scansione completa in background scaduta, restano le porte mirate", ip)
        journal.add("detail", "journal.fullports_failed", icon="alert", ip=ip)
        return
    await _save_found_ports(device_id, ip, _ports_found(hosts))


async def _save_found_ports(device_id: str, ip: str, found: list[dict]) -> None:
    """The ports of the full scan joined to the card as it is NOW (it may have changed while nmap ran), the services read, the page and the journal told."""
    current = next((d for d in devices_config.load_devices() if d["id"] == device_id), None)
    if not current:
        return
    info = dict(current.get("scan_info") or {})
    before = len(info.get("ports") or [])
    info["ports"] = merge_ports(info.get("ports"), found)
    info["full_ports_at"] = time.time()
    await _read_services(info, ip)
    devices_config.update_scan_info(device_id, info)
    await state.refresh_device(device_id, force=True)
    added = len(info["ports"]) - before
    logger.info("%s: scansione completa in background terminata, %d porte (%+d)", ip, len(info["ports"]), added)
    journal.add("detail", "journal.fullports", icon="magnify", ip=ip, ports=len(info["ports"]), added=max(added, 0))


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
