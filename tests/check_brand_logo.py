"""Brand logos: the table is consistent, a brand finds its logo, and the logo follows the brand shown now."""
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import brand_logo, brands, ha_data, i18n  # noqa: E402

i18n.use("en")

# --- the table and the files agree
table = json.loads(brand_logo.DATA_PATH.read_text(encoding="utf-8"))
assert table["schema"] == 1 and table["logos"]
ids, keys = set(), {}
for entry in table["logos"]:
    lid = entry["id"]
    assert re.fullmatch(r"[a-z0-9-]+", lid) and lid not in ids, lid
    ids.add(lid)
    src = entry["source"]
    assert src.split(":")[0] in table["sources"], (lid, src)                      # every source has its licence listed
    assert entry.get("color") is None or re.fullmatch(r"#[0-9a-fA-F]{6}", entry["color"]), (lid, entry.get("color"))
    svg = (brand_logo.LOGO_DIR / f"{lid}.svg").read_text(encoding="utf-8")
    assert svg.startswith("<svg") and 'viewBox="' in svg and len(svg) < 12000, lid
    assert not re.search(r"<script|<style|<title|\sfill=|\sstyle=|\sclass=|<image", svg), lid   # shape only: the page colours it
    for name in [lid, *entry["names"]]:
        k = brand_logo.slug(name)
        assert keys.setdefault(k, lid) == lid, f"{name!r} points to {keys[k]} and {lid}"   # a name never means two logos
files = {p.stem for p in brand_logo.LOGO_DIR.glob("*.svg")}
assert files == ids, ("files without a row or rows without a file", files ^ ids)

# --- a brand finds its logo, whatever the spelling
for brand, expected in [("Apple", "apple"), ("TP-Link", "tplink"), ("tp link", "tplink"), ("TPLINK", "tplink"),
                        ("AVM", "fritz"), ("FRITZ!Box", "fritz"), ("Tasmota", "tasmota"), ("ESPHome", "esphome"),
                        ("Shelly", "shelly"), ("Node-RED", "nodered"), ("Home Assistant", "homeassistant"),
                        ("Google", "google"), ("Amazon", "amazon"), ("Hikvision", "hikvision"), ("MSI", "msi")]:
    found = brand_logo.logo_for(brand)
    assert found and found["id"] == expected, (brand, found)
# no logo: unknown brands, brands without a free logo, chip makers, nothing
for brand in (None, "", "Magic Home", "Milesight", "Brand Never Seen", "Espressif", "Realtek"):
    assert brand_logo.logo_for(brand) is None, brand

# --- the brand rules behind it
assert brands.known_brand("Zengge") == "Magic Home" and brands.normalize_brand("JM Zengge Co., Ltd") == "Magic Home"
assert brands.refine_brand(None, names=["MagicHome-1A2B"]) == "Magic Home"
assert brands.refine_brand("Espressif Inc.", names=["Gateway"], web_text="Tasmota") == "Tasmota"
# the software running on the device wins over the maker of the hardware (a Sonoff flashed with Tasmota)
assert brands.refine_brand("ITEAD", names=["Sonoff ZBBridge"], web_text="Tasmota 15.6") == "Tasmota"
assert brands.refine_brand("Espressif Inc.", names=["Lamp"], web_text="ESPHome") == "ESPHome"

# --- the logo is worked out from the brand shown now: it follows a change, by hand or automatic
dev = {"id": "d1", "ip": "10.0.0.5", "name": "Thing", "extra": {}, "scanned_ports": [], "brand": "Shelly"}
assert ha_data.compact_device(dev, {})["logo"] == "shelly"
assert ha_data.compact_device({**dev, "brand": "Apple"}, {})["logo"] == "apple"
assert ha_data.compact_device({**dev, "brand": "Magic Home"}, {})["logo"] is None
assert ha_data.compact_device({**dev, "brand": None}, {})["logo"] is None
assert ha_data.compact_device(dev, {})["logo_color"] == "#4495D1"
print("TUTTO OK")
