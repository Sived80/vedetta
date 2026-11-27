# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The inventory by address of a network behind the router (1.0 step P11, decisions 1A and 2A): what one ping sweep of the network found,
merged with what is already known of it. ARP does not cross the router (K10), so here the key is the address, not the MAC.

merge() is pure: it is handed the sweep (the addresses that answered), the rows of the network written before (routed_seen), the trackers of
a router integration of Home Assistant (MAC and name by address), the mDNS names by address, and what the rest of Vedetta already knows
(the cards, the MACs seen). It gives the rows to write and the new devices to alert. Rules:
- the first sweep of a network (no row of it yet) is the starting point: what answers goes in the list of new devices (the person adds or
  ignores it from there) but nothing is alerted, as at the first install; a sweep where nothing answered is not a starting point (it waits);
- afterwards an address never seen that is not a card is new and alerted once; a card is never new: an address of a card without a link,
  a configured MAC (a linked card, an adopted device of Home Assistant);
- the MAC comes only from Home Assistant, never made up; when a MAC is known, the rule by MAC holds: a MAC already seen elsewhere is not a new
  device (a "new" one stays new, without a second alert), and a different MAC at an address already seen is another device;
- the ignored ones (by MAC, address or name) are not written at all, like the ignored MACs of the home network.
Without the router integration a device that changes address looks new: the panel «Networks» says so."""
import ipaddress
from dataclasses import dataclass, field

from .inventory import KEEP_S

LISTED_S = KEEP_S          # a new device behind the router stays in the list while it answered within this time (as the inventory keeps a device)


@dataclass(frozen=True)
class Known:
    """What the rest of Vedetta knows, read once per sweep: MACs are uppercase with colons."""
    card_ips: frozenset = frozenset()       # the addresses of the cards without a link
    card_macs: frozenset = frozenset()      # configured MACs: linked cards, adopted devices of Home Assistant
    macs: dict = field(default_factory=dict)  # MAC -> status ("new", "known", "ignored") of every MAC already seen, here or on another network


NOTHING = Known()


@dataclass(frozen=True)
class Outcome:
    rows: list          # the rows to write: {network, ip, first_seen, last_seen, mac, host, status}
    fresh: list         # the new devices to alert: {mac, ip, hostname, first_seen, network}
    baseline: bool      # this sweep is the starting point of the network
    with_mac: int       # addresses that answered and whose MAC Home Assistant said now


def _never(mac, ip, name) -> bool:
    return False


def merge(network, answered, previous, now: float, trackers: dict | None = None, names: dict | None = None,
          known: Known = NOTHING, blocked=_never) -> Outcome:
    """One sweep of `network` merged with its rows written before (`previous`). trackers: address -> {"mac", "host", "name"} (MAC already
    normalised); names: address -> mDNS name; blocked(mac, ip, name): the ignored ones."""
    trackers, names = trackers or {}, names or {}
    sweep = _Sweep(network.id, {r["ip"]: r for r in previous if _holds(network, r.get("ip"))}, known, now)
    for ip in dict.fromkeys(answered):
        if _holds(network, ip):
            sweep.take(ip, trackers.get(ip) or {}, names.get(ip), blocked)
    return Outcome(sweep.rows, sweep.fresh, sweep.baseline, sweep.with_mac)


class _Sweep:
    """The rows and the new devices of one sweep, address by address."""

    def __init__(self, nid: str, before: dict, known: Known, now: float):
        self.nid, self.before, self.known, self.now = nid, before, known, now
        self.baseline = not before
        self.rows, self.fresh, self.with_mac = [], [], 0

    def take(self, ip: str, said: dict, mdns_name, blocked) -> None:
        mac, host = said.get("mac"), said.get("host") or said.get("name") or mdns_name
        if blocked(mac, ip, host):
            return
        self.with_mac += bool(mac)
        configured = ip in self.known.card_ips or (mac is not None and mac in self.known.card_macs)
        old = _same_device(self.before.get(ip), mac)
        if old is None:
            self._first(ip, mac, host, configured)
        else:
            self.rows.append({"network": self.nid, "ip": ip, "first_seen": old["first_seen"], "last_seen": self.now, "mac": mac or old.get("mac"),
                              "host": host or old.get("host"), "status": "known" if configured else old["status"]})

    def _first(self, ip: str, mac, host, configured: bool) -> None:
        """An address seen for the first time (or by another device): its row, and its alert when it is a new device."""
        status, alert = _first_status(mac, configured, self.baseline, self.known)
        self.rows.append({"network": self.nid, "ip": ip, "first_seen": self.now, "last_seen": self.now, "mac": mac, "host": host, "status": status})
        if alert:
            self.fresh.append({"mac": mac, "ip": ip, "hostname": host, "first_seen": self.now, "network": self.nid})


def _same_device(old: dict | None, mac) -> dict | None:
    """The row written before at this address, or None when Home Assistant now says another MAC there: another device."""
    if old is not None and old.get("mac") and mac and old["mac"] != mac:
        return None
    return old


def _first_status(mac, configured: bool, baseline: bool, known: Known) -> tuple[str, bool]:
    """(status, alert) of an address seen for the first time."""
    if configured:
        return "known", False
    if mac and mac in known.macs:
        return ("new" if known.macs[mac] == "new" else "known"), False
    return "new", not baseline


def _holds(network, ip) -> bool:
    try:
        return network.holds(ipaddress.IPv4Address(ip))
    except (ValueError, TypeError):
        return False
