"""What the manufacturer of the MAC prefix says about a device, by its role (data/brands.json, vendor_roles): brand = a real brand; component = makes chips and modules (the product is somebody else's);
virtual = the card of a hypervisor (the product is the virtual machine); dual = makes network cards AND finished products, so its name counts as a brand only when another source confirms.
From cards seen in real exports (reduced to what the classifier reads). The words of a function (the types of data/device_kinds.json) are not looked for in the name of a "dual" maker, in its vendor field
or in the name of the device (a Tenda is not a curtain); what the maker tells goes through the tables of makers, so Netgear stays a router. Component, virtual and brand makers keep telling what they tell."""
import os
import sys

os.environ.setdefault("VEDETTA_DATA_DIR", __import__("tempfile").mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import ha_data  # noqa: E402
from app.ha import ha_type_evidence as T  # noqa: E402


def card(vendor, role, name=None, ports=(), brand=None):
    return {"id": "x", "ip": "10.0.0.50", "name": name or "10.0.0.50", "name_generated": name is None, "brand": brand, "vendor": vendor, "vendor_role": role,
            "extra": {}, "scanned_ports": [{"label": p} for p in ports], "ha_registry": None, "is_mobile": False}


def read(device):
    kinds = {}
    group = ha_data.infer_type(device, None)
    T.type_scores(device, None, kinds)
    return group, max(kinds, key=kinds.get) if kinds else None


CASES = [
    # (what it is,                                   the card,                                            group now, top kind now)
    ("chip maker (component): platform knowledge stays", card("Espressif", "component"),                  "iot", None),
    ("virtual machine (virtual): the product is the VM",   card("Proxmox", "virtual"),                     "server", "server"),
    ("a real brand (brand): printer maker",                card("Epson", "brand"),                          "printer", "printer"),
    ("dual, only the vendor: Tenda, not a curtain",        card("Tenda", "dual", ports=("12598",)),         "generic", None),
    ("dual, named after its maker: Tenda-1234",            card("Tenda", "dual", name="Tenda-1234"),        "generic", None),
    ("dual, a maker the tables know (Netgear): router",    card("Netgear", "dual", ports=("80 http",)),     "router", None),
    ("a curtain whose maker is not dual: stays a curtain", card("Shelly", "component", name="Tenda salotto"), "iot", "curtain"),
]

failed = []
for label, device, group, kind in CASES:
    got = read(device)
    print("%-62s %s" % (label, got))
    if got != (group, kind):
        failed.append((label, got, (group, kind)))
assert not failed, failed
print("TUTTO OK")
