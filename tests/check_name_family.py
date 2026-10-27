"""A card that inherited the automatic name of another phone (the same address, a private MAC that changed) must not keep a name that the
system of the phone behind it contradicts: an iPhone card called "Pixel 7", an Android card called "iPhone". The names and fingerprints are
those of a real export (27 Oct 2026), the people's names replaced. Nothing chosen by hand is touched: only automatic names are judged."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.recognition import name_family  # noqa: E402
from app.scan import probe_names  # noqa: E402
from app.scan.probe_record import Facts  # noqa: E402

failed = []


def check(label, got, want):
    if got != want:
        failed.append("%s: got %r, expected %r" % (label, got, want))


# --- 1. the pure rule: the brand the name points to against the system of the phone
check("android name on an iOS phone", name_family.contradicts("Pixel 7", "ios"), True)
check("android maker name on an iOS phone", name_family.contradicts("Xiaomi-14", "ios"), True)
check("iPhone name on an Android phone", name_family.contradicts("iPhone-di-Anna", "android"), True)
check("same system, android", name_family.contradicts("Pixel-7", "android"), False)
check("same system, iOS", name_family.contradicts("iPhone-di-Anna", "ios"), False)
check("name without a brand", name_family.contradicts("S23-di-Marco", "ios"), False)
check("system not known", name_family.contradicts("Pixel 7", None), False)
check("not a phone system", name_family.contradicts("Pixel 7", "windows"), False)
check("no name", name_family.contradicts(None, "ios"), False)


# --- 2. the choice of the name on a card, with the fingerprint of the current MAC
def facts(device, dhcp_name=None, mdns_name=None, family="ios"):
    f = Facts.__new__(Facts)
    f.device, f.ip, f.dhcp_name = device, "10.0.0.8", dhcp_name
    f.scan_info = {"mdns_name": mdns_name} if mdns_name else {}
    f.identity_mac = "9a:00:00:00:00:01"
    f.family = family
    return f


def names_of(device, **kw):
    f = facts(device, **kw)
    n = probe_names.NameState(base_name=device["name"], placeholder=False, ha_stale=False)
    probe_names.choose_automatic_name(f, n, family=f.family)
    return n


wrong = {"name": "Pixel 7", "name_source": "mdns"}
n = names_of(wrong, dhcp_name="iPhone-di-Anna")
check("iPhone behind a Pixel name: its own name wins", (n.base_name, n.auto_name), ("iPhone-di-Anna", ("iPhone-di-Anna", "dhcp", True)))
n = names_of(wrong)
check("no own name: the inherited one is dropped, not shown", (n.base_name, n.auto_name), (None, None))
n = names_of(wrong, mdns_name="Pixel 7")
check("the same wrong name announced again does not come back", n.base_name, None)
n = names_of({"name": "Pixel 7", "name_source": "mdns"}, family="android")
check("same system: nothing changes", (n.base_name, n.auto_name), ("Pixel 7", None))
n = names_of({"name": "Pixel 7", "name_source": "user"})
check("a name chosen by hand is never touched", (n.base_name, n.auto_name), ("Pixel 7", None))
n = names_of({"name": "Pixel 7", "name_source": "ha_user"})
check("a name from Home Assistant is never touched", (n.base_name, n.auto_name), ("Pixel 7", None))
n = names_of(wrong, family=None)
check("system not known: nothing changes", (n.base_name, n.auto_name), ("Pixel 7", None))

if failed:
    print("FAILED:\n  " + "\n  ".join(failed))
    sys.exit(1)
print("OK")
