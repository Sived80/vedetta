"""«Delete this network» (a written network): its cards in devices.yaml, the devices of Home Assistant adopted
in it, every row of the history about it, the ignored devices of it (by MAC seen there or by an address of it: those ignored by name hold for
every network and stay) and its row in networks.json. Nothing of another network is touched (tests/check_network_purge.py). preview() gives
the numbers the page shows before asking; run() deletes and returns the ids of the cards gone, for the caller to drop them from the live state.
If one of its devices is in the list again, the network comes back as a new one (K12).
The main network is never deleted: for it the same things go except the network itself (its name stays), and the new devices start over as at
the first install (newdevices.BASELINE_KEY: the next cycle is the starting point, no alert; tests/check_network_purge_main.py)."""
from ..storage import blocklist, devices_config, network_store, newdevices, passive_store
from ..storage.history import history
from . import registry
from .model import Network


def _written(network: Network) -> bool:
    """True for a network the person wrote, still in networks.json; False for the main network; ValueError for anything else."""
    if network.id == registry.MAIN_ID:
        return False
    if not any(r.get("id") == network.id for r in network_store.rows()):
        raise ValueError(network.id)
    return True


def _cards(network: Network) -> tuple:
    """The ids of its cards and the MACs of its adopted devices of Home Assistant."""
    cards = [d["id"] for d in devices_config.load_devices() if registry.holds(network, d.get("ip"))]
    adopted = [mac for mac, item in passive_store.snapshot()["adopted"].items() if registry.holds(network, (item.get("row") or {}).get("ip"))]
    return cards, adopted


def _ignored(network: Network, macs: list) -> list:
    """The ids of the ignored entries of the network: a MAC seen in it, an address of it."""
    seen = {m.upper() for m in macs}
    return [i["id"] for i in blocklist.list_items()
            if (i["kind"] == "mac" and i["value"].upper().replace("-", ":") in seen) or (i["kind"] == "ip" and registry.holds(network, i["value"]))]


def _history(network: Network, ids: list, apply: bool, meta_keys: tuple = ()) -> dict:
    return history.purge_network(lambda ip: registry.holds(network, ip), ids, network.id, apply, meta_keys)


def preview(network: Network) -> dict:
    """{"cards": cards and adopted devices in it, "devices": MACs seen in it, "rows": rows of the history about it, "ignored": ignored entries of it}."""
    _written(network)
    cards, adopted = _cards(network)
    found = _history(network, cards + [passive_store.id_of(m) for m in adopted], False)
    return {"cards": len(cards) + len(adopted), "devices": len(found["macs"]), "rows": found["rows"], "ignored": len(_ignored(network, found["macs"]))}


def run(network: Network) -> list:
    """Delete everything about the network; the ids of the cards gone. The row of the network goes last: if anything fails, it can be done again.
    The main network stays, and its new devices start over (the next cycle is the starting point)."""
    written = _written(network)
    cards, adopted = _cards(network)
    ids = cards + [passive_store.id_of(m) for m in adopted]
    ignored = _ignored(network, _history(network, ids, False)["macs"])      # the MACs seen there, read before their rows go
    for card in cards:
        devices_config.remove_device(card)
    passive_store.forget_many(adopted)
    blocklist.remove_many(ignored)
    _history(network, ids, True, () if written else (newdevices.BASELINE_KEY,))
    if written:
        network_store.remove(network.id)
    return ids
