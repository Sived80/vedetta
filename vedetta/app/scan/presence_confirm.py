# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""Confirm before saying offline (1.0.2). A card on Home Assistant's own network that was online and whose miss in this cycle reaches the
tolerance gets one more chance before it is called offline: ONE targeted ARP request (arp-scan of its address, the tool every cycle already
uses) and a fresh read of the neighbour table (no packet). If it answers there as itself (presence.complete_with_arp: not another card's MAC)
it stays online.

Bounded so that the cycle is not delayed on a big network: only the cards about to drop are asked (usually none), at most MAX_PER_CYCLE of
them, all in one arp-scan run whose packets are INTERVAL_MS apart; arp-scan gives up on a silent address after about 1.3 s (two tries,
500 ms then 750 ms), and the whole run is killed after TIMEOUT_S. So a cycle with cards about to drop costs about 1.5 s more, at most 5 s.
Behind the router nothing changes: ARP does not cross it, the ping of the sweep (presence.complete_with_ping) stays the rule there."""
import ipaddress

from .. import netutil
from ..applog import logger
from . import presence, scan_arp

MAX_PER_CYCLE = 16
INTERVAL_MS = 20
TIMEOUT_S = 5.0


def _on_main_network(ip: str | None) -> bool:
    try:
        return bool(netutil.last_network) and ipaddress.ip_address(ip) in ipaddress.ip_network(netutil.last_network, strict=False)
    except (TypeError, ValueError):
        return False


def _about_to_drop(state, device: dict, result) -> bool:
    """Online until now, offline in this check, and this miss reaches the tolerance."""
    if not isinstance(result, dict) or result.get("online"):
        return False
    before = state.devices.get(device["id"]) or {}
    return bool(before.get("online")) and state._misses.get(device["id"], 0) + 1 >= state._miss_limit() and _on_main_network(device.get("ip"))


async def _answers(ips: list[str]) -> dict[str, dict]:
    """{ip: host} of the addresses that answer one ARP request now or that the neighbour table has just seen answer; {} on any error."""
    try:
        hosts = await scan_arp.arp_scan(ips, timeout=TIMEOUT_S, interval_ms=INTERVAL_MS)
    except Exception as exc:
        logger.debug("Conferma prima di offline non riuscita (%r)", exc)
        hosts = []
    try:
        hosts = scan_arp.with_neighbours(hosts, await scan_arp.neighbors(netutil.last_network))
    except Exception as exc:
        logger.debug("Tabella dei vicini non letta per la conferma (%r)", exc)
    wanted = set(ips)
    return {h["ip"]: h for h in hosts if h.get("ip") in wanted}


async def confirm_before_offline(state, inputs: list[dict], results: list) -> None:
    """The cards about to go offline asked once more (see above); a result that answers is made online in place."""
    waiting = [k for k, (i, r) in enumerate(zip(inputs, results)) if _about_to_drop(state, i, r)][:MAX_PER_CYCLE]
    if not waiting:
        return
    found = await _answers([inputs[k]["ip"] for k in waiting])

    async def view():
        return found

    for k in waiting:
        ip = inputs[k]["ip"]
        confirmed = await presence.complete_with_arp(results[k], inputs[k], ip, view())
        if confirmed.get("online"):
            results[k] = confirmed
        logger.debug("Conferma prima di offline: %s %s", ip, "risponde, resta online" if confirmed.get("online") else "non risponde")
