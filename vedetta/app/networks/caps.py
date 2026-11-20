"""The judge of the functions of a network, for the panel «Networks»: what Vedetta sees of the devices of one network, function by function,
and where each piece comes from.

Pure: no network, no disk, no clock. It is handed the facts of one network (Facts) and gives, for each of the 7 functions (FUNCS), one of:
- on:   {"state": "on", "source", "by"}: it works, from Vedetta ("ved"), Home Assistant ("ha") or the router ("router"), in the way `by`;
- off:  the same with the switch off: it would work, the person turned it off;
- how:  {"state": "how", "need", "ways"}: it does not work yet; each way is something the person can do (who, where, recommended or coming soon);
- soon: {"state": "soon"}: Vedetta cannot do it yet.
Only ports and model have a switch (decision 1A of 13/11): they are what `touch` already rules (presence < ports < full), the only two whose
change alters what Vedetta sends on the network. The switch says which touch turns it on and off. The main network has none: there ports
and model are always on (decision «A» of 13/11; its touch is not written anywhere). Every text is a key of the page (text_keys(), "js."),
never a sentence: the page translates.

The rules, in short: a network Home Assistant is inside (the main one, a second interface or a VLAN of the host: "direct") is seen almost
whole by Vedetta itself. Behind the router: presence by ping (K1); names from the router's DNS when they arrive, else from a router
integration of Home Assistant; MACs and the stealth devices only from such an integration; ports when touch allows them and the network
answers; model from an mDNS reflector (announcements arrive from that network), else with the ports: the search asks the devices through the
router (decision «B» of 14/11), so the model follows the switch of the ports; strays only from inside."""
import ipaddress
from dataclasses import dataclass

from .model import TOUCH

FUNCS = ("pres", "name", "mac", "port", "deep", "quiet", "stray")
SOURCES = ("ved", "ha", "router")
HA_IFACE = "eth0"            # the interface name of the example command when the host's one is not known


@dataclass(frozen=True)
class Facts:
    direct: bool                  # Home Assistant has an interface in the network (the main one included)
    main: bool                    # the main network: ports and model always on, no switch
    touch: str                    # presence, ports or full
    cidr: str = ""
    vlan: int | None = None       # the VLAN number (read from the host, or written by the person)
    answers: bool = False         # a card of the network is on now
    dns_names: bool = False       # a card of the network got its name from the router's DNS
    trackers: bool = False        # a router integration of Home Assistant tracks clients of the network (read by Vedetta)
    mdns: bool = False            # mDNS announcements arrive from addresses of the network
    snmp: bool = False            # the router's ARP table (SNMP) gave MACs of the network
    ha_ip: str | None = None      # Home Assistant's own address (the origin of the firewall rule)
    iface: str | None = None      # Home Assistant's main interface (the example command)
    ha_leg: bool = False          # Home Assistant already has an interface in this network (behind the router: Vedetta does not use it yet)


# ---- the ways: who does what, where (crumb keys; "net" stands for this network: its VLAN or its name) ----
WAYS = {
    "router_integration": ("ha", ("ha.settings", "ha.devices_services", "ha.add_integration")),
    "ha_inside": ("ha", ("ha.settings", "ha.system", "ha.network")),
    "firewall_rule": ("router", ("router.firewall", "router.rules")),
    "router_dns": ("router", ("router.dhcp", "router.settings")),
    "snmp": ("router", ("router.management", "router.snmp")),
    "mdns_reflector": ("router", ("router.network", "net", "router.mdns")),
}
BY = ("arp", "mdns_netbios", "port_probe", "upnp_mdns", "ping", "router_dns", "router_integration", "mdns_reflector", "through_router", "snmp")


def _way(wid: str, facts: Facts, best: bool = False, soon: bool = False) -> dict:
    by, where = WAYS[wid]
    return {"id": wid, "by": by, "best": best, "soon": soon, "where": list(where), "params": _params(wid, facts)}


def _params(wid: str, facts: Facts) -> dict:
    if wid == "firewall_rule":
        return {"from": facts.ha_ip, "to": facts.cidr}
    if wid == "ha_inside":
        return {"cidr": facts.cidr, "vlan": facts.vlan, **({"example": _example(facts)} if facts.vlan else {})}
    if wid == "mdns_reflector":
        return {"cidr": facts.cidr, "vlan": facts.vlan}
    return {}


def _example(facts: Facts) -> str:
    """The command that gives Home Assistant an interface in the VLAN (the frontend of Home Assistant cannot create one), with an address of
    the network: the hundredth, or the last usable one of a small network. Only an example: the page says to adapt it."""
    net = ipaddress.ip_network(facts.cidr)
    address = net.network_address + (100 if net.num_addresses > 102 else net.num_addresses - 2)
    return "ha network vlan %s %d --ipv4-method static --ipv4-address %s/%d" % (facts.iface or HA_IFACE, facts.vlan, address, net.prefixlen)


def _on(source: str, by: str) -> dict:
    return {"state": "on", "source": source, "by": by}


def _how(*ways) -> dict:
    return {"state": "how", "need": "this" if len(ways) == 1 else "one", "ways": list(ways)}


SOON = {"state": "soon"}


# ---- the two switches ----
def _switch(facts: Facts, touch_on: str, touch_off: str) -> dict:
    return {"on": TOUCH.index(facts.touch) >= TOUCH.index(touch_on), "touch_on": touch_on, "touch_off": touch_off}


def _switched(cap: dict, switch: dict) -> dict:
    """A function with a switch: off when the switch is off (whatever the facts say), else as judged."""
    if not switch["on"]:
        return {"state": "off", "source": cap.get("source", "ved"), "by": cap.get("by"), "switch": switch}
    return {**cap, "switch": switch}


# ---- the judge ----
def _direct(facts: Facts) -> dict:
    port, deep = _on("ved", "port_probe"), _on("ved", "upnp_mdns")
    if not facts.main:
        port, deep = _switched(port, _switch(facts, "ports", "presence")), _switched(deep, _switch(facts, "full", "ports"))
    return {"pres": _on("ved", "arp"), "name": _on("ved", "mdns_netbios"), "mac": _on("ved", "arp"), "port": port, "deep": deep,
            "quiet": _on("ved", "arp"), "stray": SOON}


def _routed_name(facts: Facts) -> dict:
    if facts.dns_names:
        return _on("router", "router_dns")
    if facts.trackers:
        return _on("ha", "router_integration")
    return _how(_way("router_dns", facts, best=True), _way("router_integration", facts))


def _routed_port(facts: Facts) -> dict:
    """Ports through the router: on when the network answers; asked but no answer: the firewall is the likely stop."""
    switch = _switch(facts, "ports", "presence")
    if switch["on"] and not facts.answers:
        return {**_how(_way("firewall_rule", facts, best=True)), "switch": switch}
    return _switched({**_on("ved", "through_router")}, switch)


def _routed_deep(facts: Facts) -> dict:
    """The model behind the router: from the mDNS reflector when announcements arrive; else from the search of the ports (B, 14/11), with the
    same switch and the same stop as the ports."""
    if facts.mdns:
        return _on("router", "mdns_reflector")
    return _routed_port(facts)


def _routed(facts: Facts) -> dict:
    """Behind the router. Vedetta listens to ARP on the main interface only (20/11): what only Home Assistant inside the network would give
    (the hidden devices, the strays) is "coming" on every such network, and "put Home Assistant inside" is offered for MAC only as coming,
    and not at all when Home Assistant already has an interface there (it is done)."""
    tracked = _on("ha", "router_integration") if facts.trackers else None
    inside = [] if facts.ha_leg else [_way("ha_inside", facts, soon=True)]
    return {"pres": _on("ved", "ping"), "name": _routed_name(facts),
            "mac": tracked or (_on("router", "snmp") if facts.snmp else None) or _how(_way("router_integration", facts, best=True), _way("snmp", facts), *inside),
            "port": _routed_port(facts),
            "deep": _routed_deep(facts),
            "quiet": tracked or SOON,
            "stray": SOON}


def judge(facts: Facts) -> dict:
    """The 7 functions of one network, in the order of FUNCS."""
    got = _direct(facts) if facts.direct else _routed(facts)
    return {func: got[func] for func in FUNCS}


def text_keys() -> list:
    """Every text key the answers of judge() may need: what the page must translate (the panel's own labels are its business). Keys of the
    page ("js."), the only ones the browser gets."""
    keys = ["js.networks.cap." + f for f in FUNCS] + ["js.networks.how.%s.lead" % f for f in FUNCS] + ["js.networks.source." + s for s in SOURCES]
    keys += ["js.networks.by." + b for b in BY]
    keys += ["js.networks.way.%s.%s" % (w, part) for w in WAYS for part in ("title", "what", "sec")]
    return keys + ["js.networks.where." + c for c in _crumbs()]


def _crumbs() -> list:
    """The crumbs of every way, once each, in order ("net" is not a text: it is the network itself)."""
    return list(dict.fromkeys(c for _, where in WAYS.values() for c in where if c != "net"))
