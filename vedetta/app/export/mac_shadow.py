"""Shadow data per MAC: collected for analysis only, nothing here decides what a card shows.

A card is tied to an address, so when another device (or another private MAC of the same phone) starts answering at that
address the card carries over what was learned about the previous one. To judge how often that happens, and whether it
matters, two things are kept in the history database (and so in the anonymised export):
  - mac_memory: what each MAC looked like (name, brand, group, DHCP name and class) when the card showed it;
  - mac_takeover: every time the MAC behind a card changed, what the card carried over and what DHCP says of both MACs.
"""
from ..scan import dhcp
from ..storage.history import history

REFRESH_S = 6 * 3600          # an unchanged MAC is written again at most this often (last_seen)
_cache: dict[str, tuple] = {}  # mac -> (fields tuple, ts of the last write)


def _norm(mac: str | None) -> str | None:
    return mac.lower() if isinstance(mac, str) and mac else None


def _group(device: dict | None) -> str | None:
    if not device:
        return None
    try:
        from ..ha import ha_data   # late import
        return ha_data.effective_type(device)
    except Exception:
        return None


def _dhcp(mac: str | None) -> dict:
    return dhcp.seen.get(mac or "") or {}


def _fields(result: dict, mac: str) -> dict:
    d = _dhcp(mac)
    return {"name": result.get("name"), "brand": result.get("brand"), "grp": _group(result),
            "mobile_score": result.get("mobile_score"), "dhcp_name": d.get("hostname"), "dhcp_class": d.get("vendor_class")}


def observe(device_id: str, previous: dict | None, result: dict, last_mac: str | None, now: float):
    """Called for an online card with a MAC. Returns a function to run in a thread (database writes) or None."""
    mac = _norm(result.get("mac"))
    if not mac:
        return None
    old = _norm(last_mac)
    fields = _fields(result, mac)
    key = tuple(fields.values()) + (device_id, result.get("ip"))
    cached = _cache.get(mac)
    changed = cached is None or cached[0] != key
    takeover = old and old != mac
    if not changed and not takeover and now - cached[1] < REFRESH_S:
        return None
    _cache[mac] = (key, now)
    ip = result.get("ip")
    carried = {"name": (previous or {}).get("name"), "brand": (previous or {}).get("brand"), "grp": _group(previous)}

    def job():
        known = history.mac_known(mac)
        if takeover:
            history.mac_takeover_add(now, device_id, ip, old, mac, carried, _dhcp(old), _dhcp(mac), known)
        history.mac_memory_set(mac, device_id, ip, fields, now)
    return job
