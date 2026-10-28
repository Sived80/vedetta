"""Who announced the automatic name of a card, and does that name still describe the device behind the card?

A card is tied to an address. When the router hands the address of one device to another, the card carries on with the name found for the first one. The card remembers WHICH MAC
announced its automatic name (`name_mac`); the name stops applying when the shared judgement (recognition/same_device.py, policy `name`) says that the MAC behind the card is a different device from the one that
announced it. Nothing here looks at a brand, a system or a kind of device. Names chosen by hand or taken from Home Assistant are never judged (the caller). Pure: no file, no state."""
from . import naming


def same_name(a: str | None, b: str | None) -> bool:
    return bool(a) and bool(b) and a.strip().lower() == b.strip().lower()


def origin_mac(device: dict, mac: str | None, announced: list) -> str | None:
    """The MAC to remember as the one that announced the automatic name of the card, or None when there is nothing to write: only an automatic name that the MAC
    behind the card announces itself right now (a name chosen by hand or taken from Home Assistant has no origin), and only when that is not what the card already says."""
    mac = (mac or "").lower()
    if not mac or device.get("name_source") not in naming.PRIORITY or device.get("name_source") in ("ha", "ha_user"):
        return None
    if not any(same_name(device.get("name"), name) for name in announced) or (device.get("name_mac") or "").lower() == mac:
        return None
    return mac
