"""Does the automatic name of a card agree with the system of the phone behind it?

A phone with a private MAC takes the address another phone had, and the card carries on with the name found for the first one ("Pixel 7"
on an iPhone). The name is automatic, so it is not a choice of the user: when the DHCP fingerprint of the MAC now behind the card says iOS
and the brand that the name points to (the same table that names the brand of a device, data/brands.json) is not Apple, or the fingerprint
says Android and the name points to Apple, the name does not describe this phone. Pure: no file, no state.
"""
from . import brands

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
