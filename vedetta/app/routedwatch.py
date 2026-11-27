# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The ping sweep of the networks behind the router (1.0 step P11, decision 1A): every ROUTED_SWEEP_S, and when the person presses «Scan
network», each confirmed network seen through the router (not paused, at most a /22 as model.validate allows) gets one ping per address
(networks.trial.sweep: the excluded ranges never). The only question that leaves is the one of the ping adapter (K1: ICMP, no port, no name,
no ARP); what answered is merged by routedinv with what Home Assistant already said (the trackers kept by the «Home Assistant» function,
passive_store: no new reading) and with the mDNS names already heard, and written in routed_seen. The new devices go the way of those of the
home network (decision 2A): one alert each (newdevicewatch.warn_new), then the list of new devices again. The periodic sweep waits while the
periodic check is paused; the button does not."""
import asyncio
import contextlib
import time

from . import inventory_view, netutil, newdevicewatch, routedinv
from .applog import logger
from .networks import registry, trial
from .networks.model import WIDEST
from .scan import mdns_listener, router_arp
from .scan.adapters import ping
from .state import state
from .storage import blocklist, devices_config, newdevices, passive_store
from .storage.history import history

ROUTED_SWEEP_S = 900       # one sweep every 15 minutes (decision 1A)
FIRST_SWEEP_S = 60         # the first one a minute after the start, once the main network has been read
_lock = asyncio.Lock()     # one sweep at a time: the button waits for the one running and then makes its own
_task: asyncio.Task | None = None
_counts: dict = {}
_said: dict = {}           # network id -> the number of answers last written in the log: a line only when it changes


def reset_counts() -> None:
    global _counts
    _counts = {"networks": 0, "sweeps": 0, "asked": 0, "answered": 0, "with_mac": 0, "new": 0, "seconds": 0.0}


reset_counts()


def counts() -> dict:
    """What the export carries (step P11): the networks of the last sweep and, since the start, the sweeps of a network, the addresses asked,
    those that answered, those whose MAC Home Assistant said, the new devices and the seconds spent. Numbers only."""
    return {**_counts, "seconds": round(_counts["seconds"], 1)}


def routed_networks(scope) -> list:
    """The networks to sweep: confirmed (a paused or proposed one never), written, seen through the router and not through the host's own
    interface (there ARP finds the devices), at most as wide as model.validate allows."""
    return [n for n in scope.networks if n.state == "confirmed" and n.id != registry.MAIN_ID and "routed" in n.via and "direct" not in n.via
            and n.cidr.prefixlen >= WIDEST["routed"]]


async def _answers(ip: str) -> bool:
    return (await ping.probe(ip))["online"]


def _trackers() -> dict:
    """address -> {mac, host, name} of the clients a router integration of Home Assistant tracks, as the «Home Assistant» function last read
    them (nothing while that function is off)."""
    if not passive_store.enabled():
        return {}
    data = passive_store.snapshot()
    out = {}
    for r in [*data.get("candidates", {}).values(), *(item.get("row") or {} for item in data.get("adopted", {}).values())]:
        mac = newdevices.normalize_mac(r.get("mac"))
        if r.get("ip") and mac:
            out[r["ip"]] = {"mac": mac, "host": r.get("host"), "name": r.get("name")}
    return out


def _from_router(table: dict) -> dict:
    """address -> {mac} from the router's ARP table (scan/router_arp.py): the same shape as the trackers, no name (the router says none)."""
    return {ip: {"mac": newdevices.normalize_mac(mac), "host": None, "name": None} for ip, mac in table.items() if newdevices.normalize_mac(mac)}


def _mdns_names() -> dict:
    """address -> the name announced by mDNS, from what the listener already heard."""
    cards = [*mdns_listener.by_mac.values(), *mdns_listener.by_ip.values()]
    return {c["ip"]: c["name"] for c in cards if c.get("ip") and c.get("name")}


def _known() -> routedinv.Known:
    """The cards (by address when not linked, by MAC when linked or adopted from Home Assistant) and the status of every MAC already seen."""
    configs = devices_config.load_devices()
    adopted = {newdevices.normalize_mac(m) for m in passive_store.snapshot().get("adopted", {})}
    macs = {**history.routed_macs(), **{str(m).upper(): r["status"] for m, r in history.known_all().items()}}
    return routedinv.Known(frozenset(inventory_view.unlinked_ips(configs)), frozenset((inventory_view.linked_macs(configs) | adopted) - {None}), macs)


def _blocked(mac, ip, name) -> bool:
    return blocklist.matches(mac=mac, ip=ip, name=name)


async def sweep() -> list[dict]:
    """One sweep of every network behind the router; the rows the button lists: {ip, mac, hostname, last_seen} of the addresses that
    answered and are not a card."""
    async with _lock:
        cidr = netutil.last_network
        nets = routed_networks(await asyncio.to_thread(registry.scope_of, cidr)) if cidr else []
        if not nets:
            return []
        trackers, names = {**_from_router(await router_arp.table()), **await asyncio.to_thread(_trackers)}, _mdns_names()   # Home Assistant first
        known = await asyncio.to_thread(_known)
        outcomes = [await _one(net, trackers, names, known) for net in nets]
        _counts["networks"] = len(nets)
    fresh = [f for o in outcomes for f in o.fresh]
    if fresh:
        await _tell(fresh)
    return _listable(outcomes, known)


def _listable(outcomes: list, known: routedinv.Known) -> list[dict]:
    """What the button lists of a sweep: the addresses that answered and are not a card, as {ip, mac, hostname, last_seen}."""
    rows = [r for o in outcomes for r in o.rows]
    return [{"ip": r["ip"], "mac": r["mac"], "hostname": r["host"], "last_seen": r["last_seen"]}
            for r in rows if r["ip"] not in known.card_ips and r["mac"] not in known.card_macs]


async def _one(net, trackers: dict, names: dict, known: routedinv.Known) -> routedinv.Outcome:
    """The sweep of one network, written; the counts and one line of the log when something changed."""
    started = time.monotonic()
    asked, answered = await trial.sweep(net, _answers)
    previous = await asyncio.to_thread(history.routed_rows, net.id)
    out = routedinv.merge(net, answered, previous, time.time(), trackers, names, known, _blocked)
    await asyncio.to_thread(history.routed_write, out.rows)
    _counts.update(sweeps=_counts["sweeps"] + 1, asked=_counts["asked"] + len(asked), answered=_counts["answered"] + len(answered),
                   with_mac=_counts["with_mac"] + out.with_mac, new=_counts["new"] + len(out.fresh),
                   seconds=_counts["seconds"] + time.monotonic() - started)
    if out.baseline and out.rows:
        logger.info("Rete %s dietro il router: punto di partenza di %d indirizzi, nessun avviso", net.cidr, len(out.rows))
    elif _said.get(net.id) != len(answered):
        logger.info("Giro di ping sulla rete %s: %d indirizzi su %d rispondono", net.cidr, len(answered), len(asked))
    _said[net.id] = len(answered)
    return out


async def _tell(fresh: list[dict]) -> None:
    """The new devices behind the router: one alert each, as on the home network, then the list again."""
    entries = await asyncio.to_thread(lambda: [newdevices.routed_entry(f) for f in fresh])
    newdevicewatch.warn_new(entries, state.emit_alert)
    state.set_new_devices(await asyncio.to_thread(newdevices.list_new))


async def _turn() -> None:
    """One turn of the loop: a sweep, unless the periodic check is paused; a failure is logged and the next turn comes as usual."""
    if state.paused_remaining() is not None:
        return
    try:
        await sweep()
    except Exception:
        logger.exception("Giro di ping sulle reti dietro il router fallito")


async def _loop() -> None:
    await asyncio.sleep(FIRST_SWEEP_S)
    while True:
        await _turn()
        await asyncio.sleep(ROUTED_SWEEP_S)


def start() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())


async def stop() -> None:
    if _task:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _task
