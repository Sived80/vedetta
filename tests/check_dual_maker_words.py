"""The words of a function (data/device_kinds.json) are not looked for in the name of a maker of the role "dual" (data/brands.json, vendor_roles: it makes network cards AND finished products).
The test is made from the data, not from one maker: for EVERY dual maker, whatever its words are,
  - the maker alone (vendor field) gives no points for the words of a device type;
  - the maker also in the name of the device ("Tenda-1234") gives none (what the tables of makers say, Netgear -> router, MSI -> desktop, is meant and stays);
  - a word of function next to the maker in the name still counts ("<maker> printer" is a printer, as "printer" alone);
  - the same maker with another role (brand) is NOT protected: the control that tells the rule is what keeps the collision away.
The collisions of the data (a maker word that is also a word of a type) are listed, and there must be at least one, or the test would prove nothing."""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import ha_type_evidence as T  # noqa: E402

BRANDS = json.loads((Path(__file__).parent.parent / "vedetta" / "app" / "data" / "brands.json").read_text(encoding="utf-8"))
DUAL = BRANDS["vendor_roles"]["dual"]
assert len(DUAL) >= 10, DUAL


def kinds_of(vendor=None, role="dual", name=None):
    device = {"id": "x", "ip": "10.0.0.50", "name": name or "10.0.0.50", "name_generated": name is None, "brand": None, "vendor": vendor, "vendor_role": role,
              "extra": {}, "scanned_ports": [], "ha_registry": None, "is_mobile": False}
    clues = T._Clues(device, None, {}).collect()
    return sorted((c["group"], c["pts"], c["source"]) for c in clues if c["source"].startswith("parola: "))   # the words of the TYPES; the tables of makers (brand, "parola nel testo") are meant to speak


nothing = kinds_of()
word_alone = kinds_of(name="printer")
assert word_alone, "a name that says printer must give points to a type"
collisions = []
for maker in DUAL:
    assert kinds_of(maker) == nothing, "the vendor field alone must give nothing: %s -> %s" % (maker, kinds_of(maker))
    assert kinds_of(maker, name=maker) == nothing, "the maker in the name must give nothing: %s -> %s" % (maker, kinds_of(maker, name=maker))
    assert kinds_of(maker, name=maker + " printer") == word_alone, "a word of function next to the maker must still count: %s" % maker
    if kinds_of(maker, role="brand", name=maker) != nothing:
        collisions.append(maker)
print("collisions of the data (a dual maker whose words give points to a type if the rule is off):", collisions)
assert "tenda" in collisions, "no collision in the data: this test would prove nothing"

# the long words of the types are looked for as pieces of the text (not as whole words): a maker whose name holds one must be taken out of the text too, not only out of the set of words
w = T._Words("doorbell corp doorbell-1 printer", {"doorbell", "corp", "1", "printer"}, ("", set()), set(), set(), set())
cut = T._without_dual_maker(w, {"vendor": "Doorbell Corp", "vendor_role": "dual"})
assert "doorbell" not in cut.text and "corp" not in cut.text and "printer" in cut.text and cut.tokens == {"1", "printer"}, cut
assert T._without_dual_maker(w, {"vendor": "Doorbell Corp", "vendor_role": "brand"}) is w, "a maker of another role is left as it is"
assert T._without_dual_maker(w, {"vendor": None, "vendor_role": "dual"}) is w, "no vendor: nothing to take out"
print("TUTTO OK")
