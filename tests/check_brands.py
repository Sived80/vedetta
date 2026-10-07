"""Brand recognition check (runnable locally)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vedetta"))
from app.recognition.brands import normalize_brand, refine_brand  # noqa: E402
from app.recognition.vendor_lookup import lookup_registrant, lookup_vendor  # noqa: E402

# registered name -> brand
for raw, expected in [
    ("Hong Kong Bouffalo Lab Limited", "Bouffalo Lab"), ("Xiamen Milesight IoT Co., Ltd.", "Milesight"),
    ("Flextronics Computing(Suzhou)Co.,Ltd.", "Apple"), ("Amazon Technologies Inc.", "Amazon"),
    ("Allterco Robotics LTD", "Shelly"), ("Google, Inc.", "Google"), ("Espressif Inc.", "Espressif"),
    ("WNC Corporation", "Wistron NeWeb"),
]:
    got = normalize_brand(raw)
    assert got == expected, (raw, got, expected)

# prefixes: 24 bit (including recent ones) and random MACs
assert lookup_vendor("BC:24:11:00:00:A4") == "Proxmox"
assert lookup_vendor("8C:4F:00:00:00:B4") == "Espressif"
assert lookup_vendor("B0:19:21:00:00:A9") == "TP-Link"
assert lookup_vendor("7A:AD:F7:00:00:B5") is None  # U/L bit: random MAC

# the device's sources beat the prefix
assert refine_brand("Espressif", names=["shelly1-8CAAB50000A2"]) == "Shelly"
assert refine_brand(None, names=[], os_family="ios") == "Apple"
assert refine_brand("Intel", names=["MSI"], upnp_manufacturer="Micro-Star International") == "MSI"
assert refine_brand(None, names=[], web_text="Proxmox Virtual Environment") == "Proxmox"
# the prefix is the board, not the product: TP-Link only counts if the device is the gateway
assert refine_brand("TP-Link", names=["Casa"]) is None
assert refine_brand("TP-Link", names=["Casa"], is_gateway=True) == "TP-Link"
assert refine_brand("Espressif", names=[]) is None and refine_brand("Bouffalo Lab", names=[]) is None
assert refine_brand("Proxmox", names=[]) is None  # virtual MAC: the product brand is another one
assert refine_brand("Sony", names=[]) == "Sony"
# UPnP: only counts if it is a brand in the names table
assert refine_brand("TP-Link", names=[], upnp_manufacturer="Justin Maggard", is_gateway=True) == "TP-Link"  # author of MiniDLNA: not a known brand, the gateway stays
assert refine_brand("Wistron NeWeb", names=[], upnp_manufacturer="Sony Corporation") == "Sony"
assert refine_brand(None, names=[], upnp_manufacturer="Sonos, Inc.") == "Sonos"
# web title/server win over the prefix: the network card is not the product
assert refine_brand("TP-Link", names=[], web_text="pve-api-daemon/3.0") == "Proxmox"
print("OK")

# user rules in config/brands.json: precedence over the default ones
import json, tempfile, time  # noqa: E402
from app.recognition import brands  # noqa: E402

tmp = Path(tempfile.mkdtemp()) / "brands.json"
tmp.write_text(json.dumps({"aliases": [["bouffalo", "Tuya (Bouffalo)"]], "name_hints": [["^lampada", "Philips Hue"]]}), encoding="utf-8")
brands._USER_PATH = tmp
brands._cache["stamp"] = None
assert normalize_brand("Hong Kong Bouffalo Lab Limited") == "Tuya (Bouffalo)"
assert refine_brand(None, names=["lampada salotto"]) == "Philips Hue"
assert normalize_brand("Espressif Inc.") == "Espressif"  # the default ones remain valid
print("OK regole utente")

# --- rules created from the interface (config/brands.json "rules") ---
import shutil  # noqa: E402
from app.recognition import oui_update, vendor_lookup  # noqa: E402

cfg = Path(tempfile.mkdtemp())
brands._USER_PATH = cfg / "brands.json"
vendor_lookup.USER_OUI_PATH = cfg / "oui-ieee.txt"
brands._cache["stamp"] = None

# vendor: the manufacturer CONTAINS the text (case-insensitive), special characters included
brands.add_rule("vendor", "Bouffalo", "Tuya UI")
assert normalize_brand("Hong Kong Bouffalo Lab Limited") == "Tuya UI"
brands.add_rule("vendor", "Foo+Bar (X)", "FooBar")
assert normalize_brand("Acme foo+bar (x) Ltd") == "FooBar"
assert normalize_brand("Acme fooobar xx") != "FooBar"
# name: plain text, not regex
brands.add_rule("name", "lamp.+(", "Philips Hue")
assert refine_brand(None, names=["Lamp.+( salotto"]) == "Philips Hue"
assert refine_brand(None, names=["lampxxxx"]) is None
brands.add_rule("name", "shelly", "Mio Shelly")  # precedence over the default ones
assert refine_brand("Espressif", names=["shelly1-8CAAB50000A2"]) == "Mio Shelly"
# software
brands.add_rule("software", "Mio Pannello (v2)", "PannelloCo")
assert refine_brand(None, names=[], web_text="Benvenuto in MIO PANNELLO (V2)") == "PannelloCo"
assert refine_brand(None, names=[], web_text="Proxmox Virtual Environment") == "Proxmox"

# duplicates: same kind+text pair -> replaces the brand
n = len(brands.list_rules())
brands.add_rule("vendor", "bouffalo", "Altra")
assert len(brands.list_rules()) == n
assert normalize_brand("Hong Kong Bouffalo Lab Limited") == "Altra"
brands.add_rule("name", "bouffalo", "Altra")  # different kind: new rule
assert len(brands.list_rules()) == n + 1

# validation
for args, code in [(("x", "abc", "B"), "kind"), (("name", "a", "B"), "text"), (("name", " a ", "B"), "text"),
                   (("name", "a" * 81, "B"), "text"), (("name", "abc", "  "), "brand"), (("name", "abc", "b" * 61), "brand")]:
    try:
        brands.add_rule(*args)
        raise AssertionError(args)
    except ValueError as exc:
        assert str(exc) == code, (args, exc)

# deletion and preservation of the other keys
brands.update_user({"aliases": [["zzz", "ZetaBrand"]]})
assert normalize_brand("zzz corp") == "ZetaBrand"
rid = next(r["id"] for r in brands.list_rules() if r["text"] == "Foo+Bar (X)")
assert brands.delete_rule(rid) and not brands.delete_rule(rid)
assert normalize_brand("Acme foo+bar (x) Ltd") != "FooBar"
assert normalize_brand("zzz corp") == "ZetaBrand"
assert not list(cfg.glob(".brands-*.tmp"))  # no leftover temporary files
print("OK regole interfaccia")

# --- manuf conversion and rejection of files that are too small ---
sample = "Registry,Assignment,Organization Name,Organization Address\n" \
         "MA-L,000000,Xerox Corporation,Via Roma 1 Milano IT\n" \
         "MA-M,00155D4,\"Msft, Inc.\",\n" \
         "MA-L,BC2411,Proxmox Server Solutions GmbH,Wien AT\n" \
         "MA-S,70B3D5102,Long Name Srl,\n" \
         "IAB,0050C2F71,RF Code,Austin TX US\n" \
         "riga rotta\nMA-L,ZZZZZZ,Esadecimale non valido,\n"
assert oui_update.convert_ieee(sample) == ["000000 Xerox Corporation", "00155D4/28 Msft, Inc.",
                                           "BC2411 Proxmox Server Solutions GmbH", "70B3D5102/36 Long Name Srl",
                                           "0050C2F71/36 RF Code"]
# a single valid registry or several registries together (list of texts)
assert oui_update.build([sample, sample], min_blocks=1)[1] == 10
for text, code in [(sample, "too_small"), ("niente\naltro\n", "invalid")]:
    try:
        oui_update.install(text)
        raise AssertionError(code)
    except oui_update.OuiUpdateError as exc:
        assert exc.code == code, exc
assert not vendor_lookup.USER_OUI_PATH.exists()  # rejected: nothing written
assert oui_update.is_due() and not oui_update.auto_update_enabled()

big = sample + "".join(f"MA-L,{i:06X},Vendor {i},\n" for i in range(0x100000, 0x100000 + 40000))
before = vendor_lookup.oui_stats()
assert before["source"] == "bundled"
res = oui_update.install(big)
assert res["blocks"] >= 40000 and vendor_lookup.USER_OUI_PATH.exists()
after = vendor_lookup.oui_stats()
assert after["source"] == "downloaded" and after["blocks"] == res["blocks"]
assert vendor_lookup.lookup_registrant("10:00:05:00:00:01") == "Vendor 1048581"  # 0x100005
assert vendor_lookup.lookup_vendor("BC:24:11:00:00:A4") == "Proxmox"
assert not oui_update.is_due() and oui_update.meta()["blocks"] == res["blocks"]
assert normalize_brand("zzz corp") == "ZetaBrand"  # the metadata do not delete the rules
# the file in config/ reloads by itself on change (mtime) and, if it disappears, the bundled one comes back
import os  # noqa: E402
vendor_lookup.USER_OUI_PATH.write_text("# x\n" + "A0BBCC Nuova Marca\n", encoding="utf-8")
os.utime(vendor_lookup.USER_OUI_PATH, (time.time() + 5, time.time() + 5))
assert vendor_lookup.lookup_registrant("A0:BB:CC:00:00:01") == "Nuova Marca"
vendor_lookup.USER_OUI_PATH.unlink()
assert vendor_lookup.oui_stats()["source"] == "bundled" and vendor_lookup.lookup_vendor("BC:24:11:00:00:A4") == "Proxmox"
shutil.rmtree(cfg, ignore_errors=True)
print("OK aggiornamento prefissi")
