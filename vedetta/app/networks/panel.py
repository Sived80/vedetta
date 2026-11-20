"""What the panel «Networks» shows of each network beyond its row of before: its name, its VLAN, how many cards are on, whether it went
mute, and what Vedetta sees of it function by function (the judge, caps.py).

gather() reads, once per answer, what is already known elsewhere; describe() is pure and works out one network from it:
- the cards (devices.yaml) and the last presence of each (the history: activity.py says why that record);
- the host's interfaces (host_read.read_host): the VLAN of a network Home Assistant is inside;
- the clients a router integration of Home Assistant tracks (passive_store, filled only while that function is on): MACs and stealth devices;
- the mDNS announcements heard in the last day (mdns_listener): a reflector on the router brings those of another network;
- names from the router's DNS: a card whose name came from the reverse lookup (name_source "nmap": nmap asks the system's resolver, the router).
Nothing here asks a device or Home Assistant: the readings are the ones Vedetta already keeps."""
import ipaddress
import time
from dataclasses import dataclass

from ..scan import mdns_listener
from ..storage import passive_store
from ..storage.history import history
from . import activity, caps, host_read
from .model import Network

DNS_SOURCE = "nmap"            # the name source of a reverse lookup through the system's resolver (recognition/naming.py)
MDNS_RECENT_S = 24 * 3600


@dataclass(frozen=True)
class Seen:
    cards: tuple                  # (id, address, name source) of every card
    last: dict                    # history.last_presence()
    host: dict                    # host_read.read_host()
    trackers: tuple               # addresses of the clients a router integration tracks
    mdns: tuple                   # addresses heard announcing by mDNS in the last day
    own_ip: str | None
    iface: str | None
    now: float
    snmp: tuple = ()               # addresses the router's ARP table gave a MAC for (scan/router_arp.py, passed by the caller)


def gather(devices: list, own_ip: str | None, iface: str | None, snmp: tuple = ()) -> Seen:
    """What the panel needs, read once for every network of one answer."""
    now = time.time()
    cards = tuple((d.get("id"), d.get("ip"), d.get("name_source")) for d in devices)
    return Seen(cards, history.last_presence(), host_read.read_host(), _tracked(), _announcing(now), own_ip, iface, now, tuple(snmp))


def _tracked() -> tuple:
    if not passive_store.enabled():
        return ()
    data = passive_store.snapshot()
    rows = [*data.get("candidates", {}).values(), *(item.get("row") or {} for item in data.get("adopted", {}).values())]
    return tuple(r.get("ip") for r in rows if r.get("ip"))


def _announcing(now: float) -> tuple:
    cards = [*mdns_listener.by_mac.values(), *mdns_listener.by_ip.values()]
    return tuple(c.get("ip") for c in cards if c.get("ip") and now - float(c.get("seen") or 0) < MDNS_RECENT_S)


def _in(network: Network, ip) -> bool:
    try:
        return network.holds(ipaddress.IPv4Address(ip))
    except (ValueError, TypeError):
        return False


def describe(network: Network, seen: Seen, name: str | None, main: bool, answers: bool | None = None) -> dict:
    """{"name", "vlan", "on", "mute", "caps"} of one network. `name` is the one to show (the main network's default included). `answers`:
    whether the network answers, when it is known otherwise (the sweep of «try and add»); by default, a card of it is on now, or it has no card
    yet (just added: its devices are not found again yet, nothing says that it does not answer, so no firewall help)."""
    life = activity.tally(network, [(cid, ip) for cid, ip, _ in seen.cards], seen.last, seen.now)
    direct = "direct" in network.via
    vlan = (host_read.vlan_for(network.cidr, seen.host) if direct else None) or network.vlan
    facts = caps.Facts(direct=direct, main=main, touch=network.touch, cidr=str(network.cidr), vlan=vlan,
                       answers=(life["on"] > 0 or life["cards"] == 0) if answers is None else answers,
                       dns_names=any(src == DNS_SOURCE and _in(network, ip) for _, ip, src in seen.cards),
                       trackers=any(_in(network, ip) for ip in seen.trackers), mdns=any(_in(network, ip) for ip in seen.mdns),
                       snmp=any(_in(network, ip) for ip in seen.snmp), ha_ip=seen.own_ip, iface=seen.iface)
    return {"name": name, "vlan": vlan, "on": life["on"], "mute": life["mute"], "caps": caps.judge(facts)}
