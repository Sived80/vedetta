"""What the page shows of the devices that Home Assistant sees ("passive" devices): the cards in the same compact format as the devices Vedetta scans, and the list of the ones that can be adopted.

Pure (they take what passive_store keeps): no network, no disk. A passive device has no ports, no response time and no analysis: those fields are empty, and `passive` tells the page which parts of the
card to leave out. Name, type and brand come from Home Assistant, unless the user chose them: then the choice wins."""
import ipaddress

from .. import i18n
from ..recognition import brand_logo
from ..recognition.vendor_lookup import resolve_vendor_info
from ..storage import passive_store
from . import ha_data

SOURCE = "ha"


def _name(row: dict, edit: dict, mac: str) -> str:
    return edit.get("name") or row.get("name") or row.get("host") or row.get("ip") or mac.upper()


def _brand(mac: str, row: dict, edit: dict) -> tuple[dict, str | None, str | None]:
    """(vendor facts, brand shown, where it comes from): the user's choice, else the product brand the MAC and the host name say."""
    info = resolve_vendor_info(mac, None, [row["host"]] if row.get("host") else [])
    if edit.get("brand"):
        return info, edit["brand"], "user"
    return info, info["brand"], "mac" if info["brand"] else None


def _type(device: dict, edit: dict) -> str:
    return ha_data.effective_type(device, {"type_user": edit.get("type")})


def compact(mac: str, item: dict) -> dict:
    """One adopted device in the compact format of ha_data.compact_device (same keys), plus passive=True."""
    row, edit = item["row"], item.get("edit") or {}
    info, brand, brand_source = _brand(mac, row, edit)
    name = _name(row, edit, mac)
    device = {"id": passive_store.id_of(mac), "name": name, "ip": row.get("ip"), "mac": mac.upper(), "brand": brand, "vendor": info["vendor"], "vendor_role": info["vendor_role"]}
    kind = _type(device, edit)
    online = bool(row.get("online"))
    logo = brand_logo.logo_for(brand)
    return {
        "id": device["id"], "name": name, "ip": row.get("ip") or "", "port": None, "mac": device["mac"],
        "vendor": info["vendor"], "vendor_role": info["vendor_role"], "brand": brand, "brand_source": brand_source,
        "brand_confidence": None, "brand_evidence": None, "brand_declared": None,
        **ha_data._logo_fields(logo),
        "battery": None, "battery_source": None,
        "type": kind, "icon": ha_data.icon_for(device, None, kind), "is_mobile": False, "mobile_mode": "auto",
        "name_source": "user" if edit.get("name") else SOURCE, "wol_ok": False, "ha_share": False,
        "type_user": edit.get("type"), "brand_user": edit.get("brand"), "focus": False, "focus_note": None,
        "online": online, "last_seen": None if online else item.get("online_at"), "uptime": None, "signal": None,
        "latency_ms": None, "latency_color": None, "ports": [], "url": None, "title": None, "scanned_at": None,
        "web_open": None, "deep_empty_at": None,
        "attrs": [{"key": "seen_by", "label": i18n.t_or("extra.seen_by", "Seen through"), "value": i18n.t_or("extra.seen_by_ha", "Home Assistant")}],
        "passive": True, "name_user": edit.get("name"), "host_name": row.get("host"),
    }


def compact_all(data: dict) -> list[dict]:
    """The adopted devices of a snapshot of the store, in address order."""
    cards = [compact(mac, item) for mac, item in data["adopted"].items()]
    return sorted(cards, key=lambda c: (ip_key(c["ip"]), c["mac"]))


def ip_key(ip: str | None) -> int:
    """Numeric order of an address; the ones without one go last."""
    try:
        return int(ipaddress.IPv4Address(ip))
    except (ValueError, TypeError):
        return 1 << 40


def candidates(data: dict, known_macs: set, known_ips: set) -> list[dict]:
    """The clients Home Assistant sees that can be adopted: not adopted yet, and not a device Vedetta already has (by MAC or by address).
    Each row says whether it is on a network where Vedetta has devices (`same_net`), so the page can name the ones that are not."""
    own = {_net(ip) for ip in known_ips} - {None}
    out = []
    for mac, row in data["candidates"].items():
        if mac in data["adopted"] or mac.upper() in known_macs or (row.get("ip") and row["ip"] in known_ips):
            continue
        out.append({**row, "id": passive_store.id_of(mac), "net": _net(row.get("ip")), "same_net": _net(row.get("ip")) in own,
                    "type": _guess_type(mac, row)})
    return sorted(out, key=lambda r: (_net_order(data, r), ip_key(r["ip"]), r["mac"]))


def _guess_type(mac: str, row: dict) -> str:
    """The group the card will be in, from what Home Assistant says (the same rules as for any card)."""
    info, brand, _ = _brand(mac, row, {})
    device = {"id": passive_store.id_of(mac), "name": _name(row, {}, mac), "ip": row.get("ip"), "mac": mac.upper(), "brand": brand, "vendor": info["vendor"], "vendor_role": info["vendor_role"]}
    return _type(device, {})


def evidence(item: dict) -> dict:
    """The certainty of name, brand and type of an adopted device: all of it comes from Home Assistant (100) unless the user chose it by hand (100 too, said so)."""
    edit = item.get("edit") or {}
    return {key: {"certainty": 100, "basis": "manual" if edit.get(field) else "ha_source", "value": None, "rejected": [], "clues": []}
            for key, field in (("name", "name"), ("brand", "brand"), ("group", "type"))}


def _net(ip: str | None) -> str | None:
    """The /24 of an address ("192.0.2.0/24"): the network the client is on, as far as the address says (the VLAN itself is not in the data)."""
    try:
        return str(ipaddress.ip_network(ip + "/24", strict=False)) if ip else None
    except ValueError:
        return None


def _net_order(data: dict, row: dict) -> int:
    """The networks in the order Home Assistant lists them (the first client of each decides), the ones without an address last."""
    order: list = []
    for r in data["candidates"].values():
        n = _net(r.get("ip"))
        if n and n not in order:
            order.append(n)
    return order.index(row["net"]) if row["net"] in order else len(order)
