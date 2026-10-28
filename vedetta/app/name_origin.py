"""Which MAC announced the name of a card: noted whenever the MAC behind the card says the very name the card carries (the rule is in recognition/name_family.py)."""
from .recognition import name_family
from .scan import dhcp, mdns_listener
from .storage import devices_config


def remember(card: dict, mac: str | None) -> None:
    """Writes `name_mac` on the card when the MAC behind it announces the card's automatic name and the card does not say so yet (nothing is read from or written to the file otherwise)."""
    low = mac.lower() if isinstance(mac, str) else ""
    announced = [(dhcp.seen.get(low) or {}).get("hostname"), (mdns_listener.by_mac.get(low) or {}).get("name")]
    origin = name_family.origin_mac(card, low, announced)
    if origin:
        devices_config.set_name_mac(card["id"], origin)
