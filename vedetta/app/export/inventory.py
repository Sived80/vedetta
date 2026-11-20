"""The inventory for the person: one row per card, as CSV or JSON, to keep, print or put in a spreadsheet. Not the export for analysis
(that one is the zip, masked and encrypted, for the developer): here the person's own list, with the choice «hide MAC and IP».

  - the columns: name, type, brand, IP, MAC, online, last seen, first seen, area of Home Assistant;
  - sorted by IP as numbers (10.0.0.9 before 10.0.0.10), cards without an address last;
  - hide=True: IP and MAC become the same placeholders as in the export for analysis (10.0.0.x, the maker prefix kept), consistently
    in the whole file; the names stay (the person asked to hide addresses, not to lose the list);
  - CSV: a cell that begins with = + - @ or a tab or a carriage return gets a leading apostrophe, so a spreadsheet never runs a name
    a device chose for itself as a formula («=HYPERLINK(...)»)."""
import csv
import io
import ipaddress
import json
from datetime import datetime, timezone

from .anonymize import Anonymizer

COLUMNS = ("name", "type", "brand", "ip", "mac", "online", "last_seen", "first_seen", "area")
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _iso(ts) -> str | None:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds") if isinstance(ts, (int, float)) else None


def _ip_key(row: dict):
    try:
        return (0, int(ipaddress.IPv4Address(row.get("ip") or "")))
    except ValueError:
        return (1, 0)


def rows(cards: list[dict], first_seen: dict[str, float], now: float) -> list[dict]:
    """Pure: the rows of the inventory from the cards as the page shows them ({id, name, type, brand, ip, mac, online, last_seen, area})."""
    out = []
    for c in cards:
        out.append({"name": c.get("name") or "", "type": c.get("type") or "", "brand": c.get("brand") or "", "ip": c.get("ip") or "",
                    "mac": c.get("mac") or "", "online": bool(c.get("online")),
                    "last_seen": _iso(now if c.get("online") else c.get("last_seen")), "first_seen": _iso(first_seen.get(c.get("id"))),
                    "area": c.get("area") or ""})
    return sorted(out, key=_ip_key)


def hidden(table: list[dict]) -> list[dict]:
    """IP and MAC masked consistently (export/anonymize.py), the rest as it is."""
    return Anonymizer().data(table)


def safe_cell(value) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_FORMULA_START) else text


def to_csv(table: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(COLUMNS)
    for r in table:
        w.writerow([safe_cell(("yes" if r[c] else "no") if c == "online" else r[c]) for c in COLUMNS])
    return buf.getvalue()


def to_json(table: list[dict]) -> str:
    return json.dumps({"columns": list(COLUMNS), "devices": table}, ensure_ascii=False, indent=1)
