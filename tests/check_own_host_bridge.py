# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The machine Vedetta runs on, and the hosts that announce accessories of a bridge (HomeKit `_hap._tcp`).

  - Home Assistant exports accessories through a bridge: every accessory is a `_hap._tcp` instance announced from Home Assistant's own address.
    Those instances name the accessories, not the machine: they never name the card of the host, nor give it a model or a maker. The host is
    a bridge when it is the machine Vedetta runs on, or when it announces two or more different instances of such a service (any bridge on
    any host, the same way). A host that announces ONE instance is that accessory: it keeps its name and model as before;
  - the deep search (scan_mdns._best_names) follows the same rule;
  - a saved automatic name that was an accessory of the bridge is not kept, and neither is what an older deep search saved from it;
  - the machine Vedetta runs on is online while Vedetta runs: ARP never lists it (nobody asks itself "who has this IP?"), so neither its
    adapter's port nor the ARP view may decide it is gone.
Only invented values (192.0.2.x, 02:00:00:...)."""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import i18n, netutil  # noqa: E402
from app.ha import ha_data  # noqa: E402
from app.recognition import roles  # noqa: E402
from app.scan import mdns_listener, presence, presence_confirm, probe, scan_arp, scan_mdns  # noqa: E402
from app.networks import registry as _routes  # noqa: E402
_routes.ROUTE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "no-route-file")

i18n.use("en")
probe.ADAPTERS = {}
roles.roles_for = lambda ip: []
roles.upnp_types = lambda ip: []
mdns_listener.STORE_PATH = Path(tempfile.mkdtemp()) / "mdns_seen.json"

OWN_IP, OWN_MAC = "192.0.2.10", "02:00:00:00:00:10"
BRIDGE_IP, BRIDGE_MAC = "192.0.2.20", "02:00:00:00:00:20"
LAMP_IP, LAMP_MAC = "192.0.2.30", "02:00:00:00:00:30"
ARP = {BRIDGE_IP: BRIDGE_MAC.lower(), LAMP_IP: LAMP_MAC.lower()}          # the own address is never in the ARP view
mdns_listener._mac_for_ip = lambda ip: ARP.get(ip)
netutil.last_network = "192.0.2.0/24"
netutil.last_own = OWN_IP
scan_arp._interface_mac = lambda: OWN_MAC                                   # the MAC of this computer's interface (read from /sys on the host)

FAILED = []


def check(label, ok, got=None):
    print(("ok   " if ok else "FAIL ") + label + ("" if ok else f"  -> {got!r}"))
    if not ok:
        FAILED.append(label)


def hap(ip, instance, model, category):
    mdns_listener.record(ip, "_hap._tcp", instance, f'"md={model}" "ci={category}" "sf=0"')


# --- the own machine: Home Assistant with its bridge of accessories
mdns_listener.record(OWN_IP, "_home-assistant._tcp", "Home", '"location_name=Home" "version=2026.11.0"')
hap(OWN_IP, "Lamp Strip 0001", "Lamp Strip", 5)
card = mdns_listener.lookup(None, OWN_IP)
info = mdns_listener.as_scan_info(card)
check("own host: an accessory does not name it", info.get("mdns_name") == "Home", info)
check("own host: an accessory gives it no model", "mdns_model" not in info, info)
check("own host: no HomeKit category from an accessory", "hap_category" not in card, card)

# --- another host with a bridge: two or more instances
mdns_listener.record(BRIDGE_IP, "_workstation._tcp", "bridgebox", "")
hap(BRIDGE_IP, "Lamp Strip 0002", "Lamp Strip", 5)
hap(BRIDGE_IP, "Wall Plug 0003", "Wall Plug", 7)
hap(BRIDGE_IP, "Wall Plug 0003", "Wall Plug", 7)                         # the same instance again is still two accessories
info = mdns_listener.as_scan_info(mdns_listener.lookup(BRIDGE_MAC))
check("bridge host: its name is not an accessory's", info.get("mdns_name") == "bridgebox", info)
check("bridge host: no model or maker from an accessory", not {"mdns_model", "mdns_manufacturer"} & set(info), info)
check("bridge host: no HomeKit category", "hap_category" not in mdns_listener.lookup(BRIDGE_MAC), mdns_listener.lookup(BRIDGE_MAC))

# --- a real accessory: one instance, its own name and model (unchanged)
hap(LAMP_IP, "Lamp Strip 0004", "Lamp Strip", 5)
info = mdns_listener.as_scan_info(mdns_listener.lookup(LAMP_MAC))
check("one accessory: keeps its name", info.get("mdns_name") == "Lamp Strip 0004", info)
check("one accessory: keeps its model", info.get("mdns_model") == "Lamp Strip", info)
check("one accessory: keeps its category", mdns_listener.lookup(LAMP_MAC).get("hap_category") == 5, mdns_listener.lookup(LAMP_MAC))

# --- an older memory: the accessory had already named the host before the second one came
mdns_listener.by_mac["02:00:00:00:00:21"] = {"name": "Lamp Strip 0005", "score": 2, "model": "Lamp Strip", "hap_category": 5,
                                             "services": ["_hap._tcp"], "ip": "192.0.2.21", "seen": 1.0}
ARP["192.0.2.21"] = "02:00:00:00:00:21"
hap("192.0.2.21", "Lamp Strip 0005", "Lamp Strip", 5)
hap("192.0.2.21", "Wall Plug 0006", "Wall Plug", 7)
old = mdns_listener.lookup("02:00:00:00:00:21")
check("old memory: the accessory's name and model are taken away", not {"name", "model", "hap_category"} & set(old), old)

# --- the deep search: the same rule
found = [("_home-assistant._tcp", "Home", OWN_IP, '"location_name=Home"'), ("_hap._tcp", "Lamp Strip 0001", OWN_IP, '"md=Lamp Strip" "ci=5"'),
         ("_hap._tcp", "Lamp Strip 0002", BRIDGE_IP, '"md=Lamp Strip"'), ("_hap._tcp", "Wall Plug 0003", BRIDGE_IP, '"md=Wall Plug"'),
         ("_hap._tcp", "Lamp Strip 0004", LAMP_IP, '"md=Lamp Strip"'), ("_hap._tcp", "Lamp Strip 0009", "192.0.2.40", '"md=Lamp Strip"')]
best, meta = scan_mdns._best_names(found)
check("deep search: the own host is named by its own service", best.get(OWN_IP, (0, None))[1] == "Home", best.get(OWN_IP))
check("deep search: the own host gets no model from an accessory", "model" not in meta.get(OWN_IP, {}), meta.get(OWN_IP))
check("deep search: a bridge host gets no accessory name", BRIDGE_IP not in best, best.get(BRIDGE_IP))
check("deep search: a bridge host gets no accessory model", "model" not in meta.get(BRIDGE_IP, {}), meta.get(BRIDGE_IP))
check("deep search: one accessory keeps its name and model", best.get(LAMP_IP, (0, None))[1] == "Lamp Strip 0004" and meta[LAMP_IP].get("model") == "Lamp Strip",
      (best.get(LAMP_IP), meta.get(LAMP_IP)))


# --- the card of the own machine, as a cycle builds it
def port(label, cat="other"):
    return {"label": label, "confirmed": False, "category": cat}


HA_CARD = {"id": "ha", "name": "Lamp Strip 0001", "name_source": "mdns", "ip": OWN_IP, "port": 8123, "adapter": "generic",
           "scan_info": {"http_title": "Home Assistant", "mdns_name": "Lamp Strip 0001", "mdns_model": "Lamp Strip",
                         "mdns_services": "_hap._tcp, _home-assistant._tcp", "ports": [port("8123 · polipo", "web"), port("21064 · unknown")]}}


async def empty_view():
    return {}


res = asyncio.run(probe.probe_device(HA_CARD, empty_view()))
check("own card: online while Vedetta runs on it (no ARP answer, port not asked)", res.get("online") is True, res.get("online"))
check("own card: its MAC is the interface's", res.get("mac") == OWN_MAC, res.get("mac"))
check("own card: not named after an accessory", "lamp strip" not in (res.get("name") or "").lower(), res.get("name"))
check("own card: the name Home Assistant announces for itself replaces the saved one", res.get("name") == "Home" and (res.get("auto_name") or ())[:1] == ("Home",),
      (res.get("name"), res.get("auto_name")))
check("own card: the accessory's model is not its model", "Lamp Strip" not in str(res.get("extra", {}).get("mdns_model")), res.get("extra"))
check("own card: Home Assistant", ha_data.best_kind(res) == "homeassistant", (ha_data.infer_type(res), ha_data.best_kind(res)))
other = asyncio.run(probe.probe_device({**HA_CARD, "id": "x", "ip": "192.0.2.50", "name": "Box", "name_source": "user"}, empty_view()))
check("another card with no answer stays offline", other.get("online") is False, other.get("online"))


# --- the confirmation before offline asks ARP: the own address never answers there, it answers by itself
async def confirm():
    class St:
        devices = {"ha": {"online": True}}
        _misses = {"ha": 5}

        @staticmethod
        def _miss_limit():
            return 1

    async def silent(ips, **kw):
        return []

    async def no_neighbours(net=None):
        return []
    scan_arp.arp_scan, scan_arp.neighbors = silent, no_neighbours
    results = [{"online": False}]
    await presence_confirm.confirm_before_offline(St, [{**HA_CARD, "link": None}], results)
    return results[0]


check("own card: the confirmation before offline keeps it online", asyncio.run(confirm()).get("online") is True)
check("presence: the own address answers with its MAC", asyncio.run(presence.complete_with_arp({"online": False}, {"link": None}, OWN_IP, empty_view())).get("mac") == OWN_MAC)

# --- privacy: the accessories a bridge announced (and the name the host gave itself) are names the export masks, each on its own
import json  # noqa: E402
from app.export import anonymize, export_zip  # noqa: E402
hap(BRIDGE_IP, "Lamp of Leo", "Lamp Strip", 5)
anon = anonymize.Anonymizer()
export_zip._add_registry_names(anon)
masked = json.dumps(anon.data({"by_mac": mdns_listener.by_mac, "by_ip": mdns_listener.by_ip}, "mdns_seen"))
check("export: an accessory's name is masked", "Leo" not in masked, [k for c in mdns_listener.by_mac.values() for k in c.get("accessories") or ()])
check("export: two accessories are two devices", len({anon.text("Lamp of Leo"), anon.text("Wall Plug 0003")}) == 2, (anon.text("Lamp of Leo"), anon.text("Wall Plug 0003")))

if FAILED:
    sys.exit(f"{len(FAILED)} FAILED")
print("ALL OK")
