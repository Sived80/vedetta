"""A card that inherited the automatic name of another phone (the same address, a private MAC that changed) must not keep a name that the
system of the phone behind it contradicts: an iPhone card called "Pixel 7", an Android card called "iPhone". The names and fingerprints are
those of a real export (27 Oct 2026), the people's names replaced. Nothing chosen by hand is touched: only automatic names are judged."""
import os
import sys
import tempfile

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())      # never the real folder of the developer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.recognition import name_family  # noqa: E402
from app.scan import dhcp, probe_names  # noqa: E402
from app.storage import devices_config  # noqa: E402
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

# --- 4. generic names: the card remembers WHICH MAC announced its name, and the name is dropped when that MAC ran another phone system than the one now behind the card
ANDROID_PRL = "1,3,6,15,26,28,51,58,59,43,114,108"
dhcp.seen["c6:00:00:00:00:21"] = {"hostname": "android-model-1", "vendor_class": "android-dhcp-15", "prl": ANDROID_PRL}
dhcp.seen["c6:00:00:00:00:99"] = {"hostname": "other", "vendor_class": "android-dhcp-15", "prl": ANDROID_PRL}
check("system changed, android to iOS", name_family.system_changed("android", "ios"), True)
check("system changed, iOS to android", name_family.system_changed("ios", "android"), True)
check("same system", name_family.system_changed("android", "android"), False)
check("old system not known", name_family.system_changed(None, "ios"), False)
check("new system not known", name_family.system_changed("android", None), False)
check("not a phone system", name_family.system_changed("windows", "ios"), False)

auto = {"name": "android-model-1", "name_source": "dhcp"}
check("the MAC that announces the name is remembered", name_family.origin_mac(auto, "C6:00:00:00:00:21", ["Android-Model-1"]), "c6:00:00:00:00:21")
check("another name announced: nothing to remember", name_family.origin_mac(auto, "c6:00:00:00:00:21", [None, "other"]), None)
check("already remembered: nothing to write", name_family.origin_mac({**auto, "name_mac": "c6:00:00:00:00:21"}, "c6:00:00:00:00:21", ["android-model-1"]), None)
check("the name moves to the MAC that announces it now", name_family.origin_mac({**auto, "name_mac": "c6:00:00:00:00:99"}, "c6:00:00:00:00:21", ["android-model-1"]), "c6:00:00:00:00:21")
check("a name chosen by hand has no origin", name_family.origin_mac({**auto, "name_source": "user"}, "c6:00:00:00:00:21", ["android-model-1"]), None)
check("a name from Home Assistant has no origin", name_family.origin_mac({**auto, "name_source": "ha"}, "c6:00:00:00:00:21", ["android-model-1"]), None)
check("no MAC, no origin", name_family.origin_mac(auto, None, ["android-model-1"]), None)

generic = {"name": "android-model-1", "name_source": "dhcp", "name_mac": "c6:00:00:00:00:21"}
n = names_of(generic)
check("iPhone behind a name announced by an Android: dropped, no own name", (n.base_name, n.auto_name), (None, None))
n = names_of(generic, dhcp_name="iPhone-di-Anna")
check("iPhone behind a name announced by an Android: its own name wins", (n.base_name, n.auto_name), ("iPhone-di-Anna", ("iPhone-di-Anna", "dhcp", True)))
n = names_of(generic, mdns_name="android-model-1")
check("the stale name announced again by the cache does not come back", n.base_name, None)
n = names_of(generic, family="android")
check("same system behind the card: nothing changes", (n.base_name, n.auto_name), ("android-model-1", None))
n = names_of({**generic, "name_mac": "aa:aa:aa:aa:aa:aa"})
check("the remembered MAC has no fingerprint: nothing changes", (n.base_name, n.auto_name), ("android-model-1", None))
n = names_of({**generic, "name_source": "user"})
check("a name chosen by hand is never judged", (n.base_name, n.auto_name), ("android-model-1", None))
n = names_of(generic, family=None)
check("the system behind the card is not known: nothing changes", (n.base_name, n.auto_name), ("android-model-1", None))

# --- 5. the card file keeps the origin of the name
devices_config.add_devices([{"ip": "10.9.0.20", "name": "android-model-1", "name_source": "dhcp"}])
card_id = devices_config.load_devices()[0]["id"]
devices_config.set_name_mac(card_id, "C6:00:00:00:00:21")
check("origin saved, lower case", devices_config.load_devices()[0].get("name_mac"), "c6:00:00:00:00:21")
devices_config.update_auto_name(card_id, "iPhone-di-Anna", "dhcp", force=True, mac="5A:00:00:00:00:22")
card = devices_config.load_devices()[0]
check("a new automatic name takes the MAC that announced it", (card["name"], card.get("name_mac")), ("iPhone-di-Anna", "5a:00:00:00:00:22"))

if failed:
    print("FAILED:\n  " + "\n  ".join(failed))
    sys.exit(1)
print("OK")
