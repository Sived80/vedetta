"""Whose answer is an ARP answer. Presence on a LAN is "somebody answers ARP at the address of the card" (scan/probe.py), but an address can pass to another
device (DHCP): then the answer is another device's, and the card of the one that left must not be kept online by it.

Since 1.0 step P5 the probe is told the card's usable link (linkview: a link stable for two judgements) and the usable links of the other cards:
  - a linked card is online by ITS MAC (macpresence.at_address): another MAC at its address is not this card; a MAC the verdict calls lent or
    virtual (a repeater answering for the clients behind it) keeps the rule of before; whether its MAC answers elsewhere is decided after the
    probes, by the cycle (state_cycle);
  - a card without a usable link is online when somebody answers at its address, unless that MAC is another card's usable link (one guard,
    decision 3A of 12/11).
The machine the app runs on is never in the ARP view (nobody asks itself "who has this IP?"): its own address answers by itself.
Pure but for the verdict it asks (macverdict, in memory) and the MAC of this computer's interface (scan_arp.own_answer)."""
import asyncio

from .. import macpresence, macverdict
from ..networks import registry
from . import scan_arp, touch_policy
from .adapters import ping


def mac_key(mac) -> str:
    return str(mac or "").strip().lower()


def _not_this_card(device: dict, host: dict) -> bool:
    """The answer at the address is positively another device's: for a linked card any MAC but its own (lent ones excepted), for the others the
    usable link of another card."""
    link = device.get("link")
    if link:
        return macpresence.at_address(link, host, macverdict.shared) == "other"
    return mac_key(host.get("mac")) in (device.get("links_of_others") or ())


def _mac_here(device: dict, host: dict) -> str | None:
    """The MAC the answer gives the card: its own link when it is among the answers (also the second of a double answer), else the first."""
    link = device.get("link")
    if link and macpresence.at_address(link, host, macverdict.shared) == "mine" and mac_key(host.get("mac")) != mac_key(link):
        return link
    return host.get("mac")


async def complete_with_arp(result: dict, device: dict, ip: str, arp_task) -> dict:
    """The adapter's result completed by the ARP view: an answer at the address makes the device online (and gives its MAC), unless the answer is positively another device's.
    The own address of this computer always answers (scan_arp.own_answer): it is held by this computer, so no other device is there."""
    if arp_task is None:
        return result
    arp = await arp_task
    own = scan_arp.own_answer(ip)         # this computer's own address: ARP never lists it, yet it is there while the app runs
    arp_info = arp.get(ip) or own
    if not arp_info:
        return result
    if own is None and _not_this_card(device, arp_info):
        return {"online": False}                                # the address passed to another device: this card is not there
    if not result.get("online"):
        result = {**result, "online": True}
    if not result.get("mac"):
        result["mac"] = _mac_here(device, arp_info)
    return result


async def complete_with_ping(result: dict, ip: str, *, routed: bool, may_touch: bool, adapter, ask) -> dict:
    """Behind the router ARP never answers, so a card whose port is closed (a UniFi without port 80, Home Assistant on 8123, a device with no
    open port) would stay offline while it answers the ping of the sweep (decision A of 15/11): there, when the adapter said offline, one ICMP
    echo (ask, the ping adapter) decides. Never on the home network, never for a card that may not be touched or whose adapter is the ping."""
    if result.get("online") or not routed or not may_touch or adapter == "ping":
        return result
    if (await ask(ip))["online"]:
        return {**result, "online": True}
    return result


_PORT_CLOSED: set[str] = set()   # cards behind the router whose adapter said offline at their last check (their port is closed)


def _pingable(device: dict, ip: str) -> bool:
    return registry.through_router(ip) and touch_policy.may_touch(device) and touch_policy.adapter_of(device) != "ping"


def start_ping(device: dict, ip: str):
    """For a card behind the router whose port was closed at the last check, the ping starts together with the adapter instead of after it:
    a check waits for the slower of the two, not their sum (an offline card cost the adapter's timeout plus the ping's). None otherwise."""
    if ip in _PORT_CLOSED and _pingable(device, ip):
        return asyncio.ensure_future(ping.probe(ip))
    return None


def _remember_port(adapter_result: dict, device: dict, ip: str) -> None:
    if adapter_result.get("online") or not _pingable(device, ip):
        _PORT_CLOSED.discard(ip)
    else:
        _PORT_CLOSED.add(ip)


async def complete(result: dict, device: dict, ip: str, arp_task, early=None) -> dict:
    """The adapter's result completed by the ARP view and, for a card behind the router, by one ping (complete_with_ping): the ping started
    early by start_ping when there is one, else a new one."""
    _remember_port(result, device, ip)
    result = await complete_with_arp(result, device, ip, arp_task)
    ask = ping.probe
    if early is not None:
        async def ask(_ip):
            return await early
    try:
        return await complete_with_ping(result, ip, routed=registry.through_router(ip), may_touch=touch_policy.may_touch(device),
                                        adapter=touch_policy.adapter_of(device), ask=ask)
    finally:
        if early is not None and not early.done():
            early.cancel()   # the adapter said online: the early ping is not needed
