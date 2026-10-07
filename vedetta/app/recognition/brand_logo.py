"""Logo of a brand, for the cards, the list and the device sheet.

The table data/brand_logos.json says which brands have a logo file (static/ha/logos/<id>.svg) and under which
names they can show up. The logo is never stored on a device: it is worked out from the brand the device shows
at that moment, so a brand changed by hand or by a new clue changes the logo with it, and a brand without a
logo simply shows none (no placeholder)."""
import json
import re
from functools import lru_cache
from pathlib import Path

from . import brands

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "brand_logos.json"
LOGO_DIR = Path(__file__).resolve().parent.parent / "static" / "ha" / "logos"


def slug(text: str | None) -> str:
    """Letters and digits only, lowercase: "TP-Link", "tp link" and "TPLink" are the same key."""
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


@lru_cache(maxsize=1)
def _index() -> dict[str, dict]:
    try:
        table = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    index: dict[str, dict] = {}
    for entry in table.get("logos", []):
        for name in [entry.get("id"), *(entry.get("names") or [])]:
            key = slug(name)
            if key:
                index.setdefault(key, entry)
    return index


def logo_for(brand: str | None) -> dict | None:
    """{"id": file name without extension, "color": brand colour or None}, or None when the brand has no logo.
    Chip and board makers (Espressif, Realtek...) are not product brands: they never get a logo."""
    if not brand or brands.vendor_role(brand) == "component":
        return None
    entry = _index().get(slug(brand))
    if not entry or not (LOGO_DIR / f"{entry['id']}.svg").exists():
        return None
    return {"id": entry["id"], "color": entry.get("color")}
