"""Who announced the automatic name of a card, and does that name still describe the device behind the card?

A card is tied to an address. When the router hands the address of one device to another, the card carries on with the name found for the first one. The card remembers WHICH MAC
announced its automatic name (`name_mac`); the name stops applying when the MAC behind the card now says something different about the device itself in its DHCP requests: the parameter
request list (option 55, in its order) and the vendor class (option 60), RFC 2132. Nothing here looks at a brand, a system or a kind of device: any two different fingerprints on two
different MACs. The vetoes (a MAC that answers for several addresses identifies nobody; names chosen by hand or taken from Home Assistant are never judged) are applied by the caller.
Pure: no file, no state."""
from . import naming


def fingerprint(entry: dict | None) -> tuple[str, str] | None:
    """(parameter request list, vendor class) of a DHCP entry, the class read without case or spaces; None when the MAC sent neither."""
    entry = entry or {}
    prl, vendor_class = entry.get("prl") or "", (entry.get("vendor_class") or "").strip().lower()
    return (prl, vendor_class) if prl or vendor_class else None


def different_device(old_entry: dict | None, new_entry: dict | None) -> bool:
    """Both MACs sent a fingerprint and the two are not the same."""
    old, new = fingerprint(old_entry), fingerprint(new_entry)
    return old is not None and new is not None and old != new


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
