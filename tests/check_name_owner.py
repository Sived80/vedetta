"""A card keeps the automatic name that one MAC announced (`name_mac`). When ANOTHER device takes the address (the router hands it out again), the name must not stay: the MAC that announced it
and the MAC that answers now say different things about the device itself in their DHCP requests (the parameter request list, option 55, and the vendor class, option 60: RFC 2132). The rule does
not look at brands, systems or kinds of device: any two different fingerprints on two different MACs. A MAC that answers for several addresses (a repeater lending its MAC) identifies nobody and never
counts; a name chosen by hand or taken from Home Assistant is never judged. The fingerprints below are made up."""
import os
import sys
import tempfile

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())      # never the real folder of the developer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.recognition import name_owner  # noqa: E402
from app.scan import dhcp, probe_names  # noqa: E402
from app.storage import devices_config  # noqa: E402
from app.scan.probe_record import Facts  # noqa: E402

failed = []


def check(label, got, want):
    if got != want:
        failed.append("%s: got %r, expected %r" % (label, got, want))


FP_A = {"prl": "1,3,6,15,26", "vendor_class": "kind-a-1"}
FP_B = {"prl": "1,121,3,6,15", "vendor_class": ""}
FP_C = {"prl": "1,15,3,6", "vendor_class": "Kind-C 5.0"}
MAC_A, MAC_B, MAC_C, NOW = "c6:00:00:00:00:21", "5a:00:00:00:00:22", "3c:00:00:00:00:31", "9a:00:00:00:00:01"
dhcp.seen[MAC_A], dhcp.seen[MAC_B], dhcp.seen[MAC_C] = dict(FP_A, hostname="name-a"), dict(FP_B), dict(FP_C, hostname="name-c")

# --- 1. what a MAC says about the device itself
check("fingerprint: list and class", name_owner.fingerprint(FP_A), ("1,3,6,15,26", "kind-a-1"))
check("fingerprint: only the list", name_owner.fingerprint(FP_B), ("1,121,3,6,15", ""))
check("fingerprint: the class is read without case or spaces", name_owner.fingerprint({"prl": "1,3", "vendor_class": "  Kind-A-1 "}), ("1,3", "kind-a-1"))
check("fingerprint: nothing sent", name_owner.fingerprint({"hostname": "x"}), None)
check("fingerprint: no entry", name_owner.fingerprint(None), None)
check("different: two fingerprints", name_owner.different_device(FP_A, FP_B), True)
check("different: the order of the list counts", name_owner.different_device({"prl": "1,3,6"}, {"prl": "3,1,6"}), True)
check("different: the same fingerprint", name_owner.different_device(FP_A, dict(FP_A, hostname="other")), False)
check("different: the same class in another case", name_owner.different_device({"prl": "1", "vendor_class": "A B"}, {"prl": "1", "vendor_class": "a b"}), False)
check("different: one is not known", name_owner.different_device(FP_A, None), False)
check("different: the other is not known", name_owner.different_device({}, FP_B), False)

# --- 2. the origin of a name
auto = {"name": "name-a", "name_source": "dhcp"}
check("the MAC that announces the name is remembered", name_owner.origin_mac(auto, MAC_A.upper(), ["Name-A"]), MAC_A)
check("another name announced: nothing to remember", name_owner.origin_mac(auto, MAC_A, [None, "other"]), None)
check("already remembered: nothing to write", name_owner.origin_mac({**auto, "name_mac": MAC_A}, MAC_A, ["name-a"]), None)
check("the name moves to the MAC that announces it now", name_owner.origin_mac({**auto, "name_mac": MAC_C}, MAC_A, ["name-a"]), MAC_A)
check("a name chosen by hand has no origin", name_owner.origin_mac({**auto, "name_source": "user"}, MAC_A, ["name-a"]), None)
check("a name from Home Assistant has no origin", name_owner.origin_mac({**auto, "name_source": "ha"}, MAC_A, ["name-a"]), None)
check("no MAC, no origin", name_owner.origin_mac(auto, None, ["name-a"]), None)


# --- 3. the choice of the name on a card
def names_of(device, dhcp_name=None, mdns_name=None, mac=NOW):
    f = Facts.__new__(Facts)
    f.device, f.ip, f.dhcp_name = device, "10.0.0.8", dhcp_name
    f.scan_info = {"mdns_name": mdns_name} if mdns_name else {}
    f.identity_mac = mac
    n = probe_names.NameState(base_name=device["name"], placeholder=False, ha_stale=False)
    probe_names.choose_automatic_name(f, n)
    return n


dhcp.seen[NOW] = dict(FP_B)
card = {"name": "name-a", "name_source": "dhcp", "name_mac": MAC_A}
n = names_of(card)
check("another device behind the card: the name is dropped, none of its own", (n.base_name, n.auto_name), (None, None))
n = names_of(card, dhcp_name="name-now")
check("another device behind the card: its own name wins", (n.base_name, n.auto_name), ("name-now", ("name-now", "dhcp", True)))
n = names_of(card, mdns_name="name-a")
check("the stale name announced again by the cache does not come back", n.base_name, None)
dhcp.seen[NOW] = dict(FP_A)
n = names_of(card)
check("the same fingerprint (the same device, a new MAC): nothing changes", (n.base_name, n.auto_name), ("name-a", None))
dhcp.seen[NOW] = dict(FP_B)
n = names_of(card, mac=MAC_A)
check("the very same MAC (a machine that changes its own system): nothing changes", (n.base_name, n.auto_name), ("name-a", None))
n = names_of({**card, "mac_shared": {NOW}})
check("the MAC answers for several addresses (a repeater): it identifies nobody", (n.base_name, n.auto_name), ("name-a", None))
n = names_of({**card, "name_mac": "aa:aa:aa:aa:aa:aa"})
check("the remembered MAC sent no fingerprint: nothing changes", (n.base_name, n.auto_name), ("name-a", None))
del dhcp.seen[NOW]
n = names_of(card)
check("the MAC behind the card sent no fingerprint: nothing changes", (n.base_name, n.auto_name), ("name-a", None))
dhcp.seen[NOW] = dict(FP_B)
n = names_of({k: v for k, v in card.items() if k != "name_mac"})
check("a card with no remembered origin (older cards): nothing changes", (n.base_name, n.auto_name), ("name-a", None))
n = names_of({**card, "name_source": "user"})
check("a name chosen by hand is never judged", (n.base_name, n.auto_name), ("name-a", None))
n = names_of({**card, "name_source": "ha_user"})
check("a name from Home Assistant is never judged", (n.base_name, n.auto_name), ("name-a", None))
dhcp.seen[NOW] = dict(FP_C)
n = names_of(card)
check("any other pair of different fingerprints is judged the same way", (n.base_name, n.auto_name), (None, None))

# --- 4. the card file keeps the origin of the name
devices_config.add_devices([{"ip": "10.9.0.20", "name": "name-a", "name_source": "dhcp"}])
card_id = devices_config.load_devices()[0]["id"]
devices_config.set_name_mac(card_id, MAC_A.upper())
check("origin saved, lower case", devices_config.load_devices()[0].get("name_mac"), MAC_A)
devices_config.update_auto_name(card_id, "name-now", "dhcp", force=True, mac=MAC_B.upper())
card_saved = devices_config.load_devices()[0]
check("a new automatic name takes the MAC that announced it", (card_saved["name"], card_saved.get("name_mac")), ("name-now", MAC_B))
devices_config.update_auto_name(card_id, "web-title", "web", force=True, mac=MAC_B)
check("a name that no MAC announced has no origin", devices_config.load_devices()[0].get("name_mac"), None)

if failed:
    print("FAILED:\n  " + "\n  ".join(failed))
    sys.exit(1)
print("OK")
