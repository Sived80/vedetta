"""A twin card's name is its main card's name and the network in brackets ("Router (VLAN 30)", twins.py). The export for the developer
masked it as "Router-2)": the name pattern stops at the last word, so the closing bracket of the name stayed behind. The placeholder must
cover the whole name; a bracket that is not the name's own stays. Invented names only."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.export import anonymize  # noqa: E402

a = anonymize.Anonymizer()
a.add_devices([(["Lab Gateway"], None, None, "router"), (["Lab Gateway (VLAN 30)"], None, None, "router"), (["Shed Sensor"], None, None, None)])
twin = a.text("Lab Gateway (VLAN 30)")
main = a.text("Lab Gateway")
assert ")" not in twin and "(" not in twin and twin != main, (twin, main)

cases = {
    "Lab Gateway (VLAN 30) is up": twin + " is up",
    "name=Lab Gateway (VLAN 30), ip": "name=" + twin + ", ip",
    "[Lab Gateway (VLAN 30)]": "[" + twin + "]",
    "(Lab Gateway (VLAN 30))": "(" + twin + ")",          # the outer brackets are the text's own
    "(Lab Gateway)": "(" + main + ")",                     # a bracket after a name without one stays
    "Lab Gateway) x": main + ") x",
    "lab_gateway_vlan_30 x": twin + " x",                  # the same name written as a host name
    "(Shed Sensor) and Lab Gateway": "(" + a.text("Shed Sensor") + ") and " + main,
}
for src, want in cases.items():
    got = a.text(src)
    assert got == want, (src, got, want)
assert a.data({"name": "Lab Gateway (VLAN 30)"}) == {"name": twin}
assert not a.leaks(a.text("the twin Lab Gateway (VLAN 30) answered"))

print("OK anon twin name")
