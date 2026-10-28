"""Does the automatic name of a card agree with the system of the phone behind it?

A phone with a private MAC takes the address another phone had, and the card carries on with the name found for the first one ("Pixel 7"
on an iPhone). The name is automatic, so it is not a choice of the user: when the DHCP fingerprint of the MAC now behind the card says iOS
and the brand that the name points to (the same table that names the brand of a device, data/brands.json) is not Apple, or the fingerprint
says Android and the name points to Apple, the name does not describe this phone. A generic name ("S23-di-...") points to no brand: for those the card
remembers WHICH MAC announced the name (`name_mac`), and the name is dropped when that MAC ran the other phone system than the one now behind the card.
Pure: no file, no state.
"""
from . import brands, naming

PHONE_SYSTEMS = ("ios", "android")


def contradicts(name: str | None, os_family: str | None) -> bool:
    """True when the brand the name points to cannot be the brand of a phone running `os_family`; False when the system is not a phone one or the name says no brand."""
    if not name or os_family not in PHONE_SYSTEMS:
        return False
    brand = brands.resolve(None, names=[name])["brand"]
    if not brand:
        return False
    is_apple = brand.lower() == "apple"
    return is_apple if os_family == "android" else not is_apple


def system_changed(old_family: str | None, new_family: str | None) -> bool:
    """The MAC that announced the name ran one phone system and the MAC behind the card now runs the other one (both must be known)."""
    return old_family in PHONE_SYSTEMS and new_family in PHONE_SYSTEMS and old_family != new_family


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
