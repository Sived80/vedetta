"""Whose answer is an ARP answer. Presence on a LAN is "somebody answers ARP at the address of the card" (scan/probe.py), but an address can pass to another
device (DHCP): then the answer is from a device that is positively another card, and the card of the one that left must not be kept online by it.

Pure: the ARP view and the map "known MAC -> card" are handed in. A MAC that answers at more than one address is a Wi-Fi repeater lending its own MAC to the
clients behind it: it identifies nobody, so it never counts against a card."""


def mac_key(mac) -> str:
    return str(mac or "").strip().lower()


def answered_by_other_card(device: dict, ip: str, arp: dict[str, dict], owner: dict[str, str]) -> bool:
    """True when the MAC that answers at `ip` is the last known MAC of a different card and answers at that address only."""
    mac = mac_key((arp.get(ip) or {}).get("mac"))
    if not mac or mac == mac_key(device.get("last_mac")):
        return False
    holder = owner.get(mac)
    if holder is None or holder == device.get("id"):
        return False
    return sum(1 for host in arp.values() if mac_key(host.get("mac")) == mac) == 1


def owners(last_macs: dict[str, str]) -> dict[str, str]:
    """Known MAC -> the one card that has it as its last MAC. A MAC claimed by two cards is left out: nobody can be told apart by it."""
    seen: dict[str, str] = {}
    shared: set[str] = set()
    for card_id, mac in last_macs.items():
        key = mac_key(mac)
        if not key:
            continue
        if key in seen:
            shared.add(key)
        seen[key] = card_id
    return {key: card_id for key, card_id in seen.items() if key not in shared}


def shared_macs(last_macs: dict[str, str]) -> set[str]:
    """The MACs that are the last MAC of two or more cards: a repeater lending its own MAC to the devices behind it. They identify nobody."""
    count: dict[str, int] = {}
    for mac in last_macs.values():
        key = mac_key(mac)
        if key:
            count[key] = count.get(key, 0) + 1
    return {key for key, n in count.items() if n >= 2}


def mac_view(last_macs: dict[str, str]) -> dict:
    """What a probe is told about the MACs of the other cards: which MAC belongs to exactly one card, and which ones several cards share."""
    return {"mac_owner": owners(last_macs), "mac_shared": shared_macs(last_macs)}


async def complete_with_arp(result: dict, device: dict, ip: str, arp_task) -> dict:
    """The adapter's result completed by the ARP view: an answer at the address makes the device online (and gives its MAC), unless the MAC that answers is positively another card's."""
    if arp_task is None:
        return result
    arp = await arp_task
    arp_info = arp.get(ip)
    if not arp_info:
        return result
    if answered_by_other_card(device, ip, arp, device.get("mac_owner") or {}):
        return {"online": False}                                # the address passed to another known device: this card is not there
    if not result.get("online"):
        result = {**result, "online": True}
    if not result.get("mac"):
        result["mac"] = arp_info.get("mac")
    return result
