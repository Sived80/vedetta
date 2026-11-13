"""What the guard of new devices sees (1.0 step P7): the inventory of the MAC layer instead of the snapshot of the last ARP read.

seen_now(arp): the ARP view of the cycle plus the devices the inventory confirms that did not answer in this cycle (inventory.build over the
ip_mac rows of the last week), in the same shape as the ARP view, so the guard compares them as before; never a candidate, never a MAC the
verdict calls lent or virtual (a repeater, a proxy ARP of the router). What ARP says now at an address wins. It also tells the list of new
devices which ones are asleep and when each MAC was last seen (decision 3A). unlinked_ips and linked_macs: "configured by address" only for
the cards without a link, a linked MAC is configured (decision 2A). Without history the view is the ARP view of before."""
import time

from . import inventory, linkview, macverdict, netutil
from .networks import registry
from .storage import newdevices
from .storage.history import history


def seen_now(arp: dict[str, dict], now: float | None = None, history=None) -> dict[str, dict]:
    """address -> {mac, vendor}: the ARP view of the cycle and the confirmed devices of the inventory that did not answer now. `history`: the
    database of the service unless another is given."""
    now = time.time() if now is None else now
    db = history if history is not None else globals()["history"]
    rows = db.rows(now - inventory.KEEP_S)
    inv = inventory.build(rows, now, _network_of(rows))
    newdevices.set_inventory({mac for (_, mac), e in inv.items() if e["state"] == "asleep"}, {mac: e["last_seen"] for (_, mac), e in inv.items()})
    return _with_confirmed(dict(arp), inv)


def _with_confirmed(out: dict[str, dict], inv: dict) -> dict[str, dict]:
    """The ARP view with the confirmed devices that did not answer now, the most recent first; what ARP says at an address wins."""
    heard = {newdevices.normalize_mac((h or {}).get("mac")) for h in out.values()}
    for (_, mac), e in sorted(inv.items(), key=lambda kv: -kv[1]["last_seen"]):
        if _may_add(mac, e, heard, out):
            out[e["ip"]] = {"mac": mac, "vendor": None}
            heard.add(mac)
    return out


def _may_add(mac: str, entry: dict, heard: set, out: dict) -> bool:
    """A confirmed device, not heard now, at an address nobody answered, and not a MAC the verdict calls lent or virtual."""
    return entry["state"] == "confirmed" and mac not in heard and entry["ip"] not in out and not macverdict.shared(mac)


def _network_of(rows: list[dict]):
    """The network of an address for the inventory: the direct network that holds it on the line (registry.direct_networks), or "main" while
    the network has not been read yet."""
    cidr = netutil.last_network
    if not cidr:
        return lambda ip: "main"
    return registry.direct_networks(sorted({r["ip"] for r in rows}), cidr).get


def _linked(card: dict) -> str | None:
    row = linkview.row(card.get("id"))
    return row["mac"].upper() if row and row.get("state") == "linked" else None


def unlinked_ips(configs: list[dict]) -> set[str]:
    """The addresses of the cards without a link: there an answer still counts as the card's (decision 2A). A card without an address fails
    as before (KeyError: the guard logs it)."""
    return {c["ip"] for c in configs if not _linked(c)}


def linked_macs(configs: list[dict]) -> set[str]:
    """The MACs of the linked cards: configured devices, whatever address they answer at."""
    return {m for m in map(_linked, configs) if m}
