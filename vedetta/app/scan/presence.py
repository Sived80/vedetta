"""Whose answer is an ARP answer. Presence on a LAN is "somebody answers ARP at the address of the card" (scan/probe.py), but an address can pass to another
device (DHCP): then the answer is another device's, and the card of the one that left must not be kept online by it.

Since 1.0 step P5 the probe is told the card's usable link (linkview: a link stable for two judgements) and the usable links of the other cards:
  - a linked card is online by ITS MAC (macpresence.at_address): another MAC at its address is not this card; a MAC the verdict calls lent or
    virtual (a repeater answering for the clients behind it) keeps the rule of before; whether its MAC answers elsewhere is decided after the
    probes, by the cycle (state_cycle);
  - a card without a usable link is online when somebody answers at its address, unless that MAC is another card's usable link (one guard,
    decision 3A of 12/11).
Pure but for the verdict it asks (macverdict, in memory)."""
from .. import macpresence, macverdict


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
    """The adapter's result completed by the ARP view: an answer at the address makes the device online (and gives its MAC), unless the answer is positively another device's."""
    if arp_task is None:
        return result
    arp = await arp_task
    arp_info = arp.get(ip)
    if not arp_info:
        return result
    if _not_this_card(device, arp_info):
        return {"online": False}                                # the address passed to another device: this card is not there
    if not result.get("online"):
        result = {**result, "online": True}
    if not result.get("mac"):
        result["mac"] = _mac_here(device, arp_info)
    return result
