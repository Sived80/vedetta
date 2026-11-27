# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The networks API, for the panel «Networks»: the main network (read from the host, never written) and the networks written by the person, with
how many cards each holds; add, change (touch, state, excluded ranges) and remove. A network that does not fit gets a 400 with the translated
reason (networks.model codes). Removing a network that still holds cards brings it back as "proposed" at the next cycle (K12): its cards are
removed from the list of devices, not here. Nothing here touches a device: the cycle and the searches read the networks through networks.registry.
For the panel v10 each row also carries its name, VLAN, the cards on now, «mute» and what Vedetta sees of it (networks.panel): fields added
on top, every field of before unchanged (tests/check_network_routes.py). The main network takes only a name (POST /api/networks/main).
«Delete this network» (networks.purge): GET /api/networks/{id}/purge gives the numbers, POST deletes; for the main network only its
devices go (the network, its name and its settings stay).
«Try and add» (networks.trial): POST /api/networks/test checks a network as an add does, pings each of its addresses once and says what answered
and what Vedetta would see of it; nothing is saved. It is declared before /api/networks/{id}, so that «test» is never taken for an id."""
import asyncio

from fastapi import APIRouter, HTTPException, Request

from .. import i18n
from ..applog import logger
from ..networks import model, panel, purge, registry, trial
from ..scan import latency
from ..state import state
from ..storage import devices_config, network_store
from .bodies import json_dict
from ..scan import router_arp

router = APIRouter()


def _row(network: model.Network, cards: list, fits: bool, seen: panel.Seen, name: str | None) -> dict:
    return {"id": network.id, "cidr": str(network.cidr), "via": sorted(network.via), "touch": network.touch, "state": network.state,
            "cards": sum(1 for ip in cards if registry.holds(network, ip)), "fits": fits,
            **panel.describe(network, seen, name, network.id == registry.MAIN_ID)}


def _state(cidr: str, own_ip: str | None) -> dict:
    main = registry.main_network(cidr)
    devices = devices_config.load_devices()
    cards = [d.get("ip") for d in devices]
    seen = panel.gather(devices, own_ip, registry.main_interface(), router_arp.last_ips())
    fitting = network_store.load(main)
    fit_ids = {n.id for n in fitting}
    main_name = network_store.main_name() or i18n.t("networks.main_name")
    return {"main": _row(main, cards, True, seen, main_name), "networks": [_row(n, cards, n.id in fit_ids, seen, n.name) for n in fitting],
            "left_out": [r.get("id") for r in network_store.rows() if r.get("id") not in fit_ids],
            "limits": {"max_networks": model.MAX_NETWORKS, "widest": model.WIDEST, "widest_other": model.WIDEST_OTHER}}


def _refused(exc: model.Rejected) -> HTTPException:
    return HTTPException(400, {"code": exc.code, "message": i18n.t(f"networks.error.{exc.code}")})


@router.get("/api/networks")
async def api_networks(request: Request):
    i18n.use_request(request)
    cidr, own = await registry.main()
    return await asyncio.to_thread(_state, cidr, own)


@router.post("/api/networks")
async def api_networks_add(request: Request):
    body = await json_dict(request)
    cidr, own = await registry.main()
    try:
        network = await asyncio.to_thread(network_store.add, body, registry.main_network(cidr))
    except model.Rejected as exc:
        raise _refused(exc)
    logger.info("Rete aggiunta: %s (%s, %s)", network.cidr, ",".join(sorted(network.via)), network.state)
    return await asyncio.to_thread(_state, cidr, own)


_TRYING = asyncio.Lock()          # one try at a time: each one sends up to a thousand pings


async def _ping(ip: str) -> bool:
    return await latency.icmp_ms(ip, latency.TIMEOUT) is not None


@router.post("/api/networks/test")
async def api_networks_test(request: Request):
    body = await json_dict(request)
    cidr, own = await registry.main()
    try:
        network = await asyncio.to_thread(network_store.check, body, registry.main_network(cidr))
        if network.cidr.prefixlen < model.WIDEST["routed"]:      # a try pings every address: never wider than a network behind the router
            raise model.Rejected("E_TOO_WIDE")
    except model.Rejected as exc:
        raise _refused(exc)
    async with _TRYING:
        asked, answering = await trial.sweep(network, _ping)
    logger.info("Rete provata: %s, %d indirizzi su %d rispondono", network.cidr, len(answering), len(asked))
    seen = await asyncio.to_thread(panel.gather, devices_config.load_devices(), own, registry.main_interface(), router_arp.last_ips())
    return trial.outcome(network, seen, asked, answering)


@router.post("/api/networks/{nid}")
async def api_networks_change(nid: str, request: Request):
    body = await json_dict(request)
    cidr, own = await registry.main()
    if nid == registry.MAIN_ID:
        return await _rename_main(body, cidr, own)
    try:
        network = await asyncio.to_thread(network_store.change, nid, body, registry.main_network(cidr))
    except model.Rejected as exc:
        raise _refused(exc)
    if network is None:
        raise HTTPException(404, i18n.t("networks.error.not_found"))
    logger.info("Rete cambiata: %s (%s, %s)", network.cidr, network.touch, network.state)
    return await asyncio.to_thread(_state, cidr, own)


async def _rename_main(body: dict, cidr: str, own: str) -> dict:
    """The main network is what the host says: of it the person writes only its name (anything else in the body is ignored, as the cidr of the others)."""
    if "name" in body:
        try:
            await asyncio.to_thread(network_store.set_main_name, body["name"])
        except model.Rejected as exc:
            raise _refused(exc)
    return await asyncio.to_thread(_state, cidr, own)


@router.delete("/api/networks/{nid}")
async def api_networks_remove(nid: str, request: Request):
    i18n.use_request(request)
    cidr, own = await registry.main()
    if not await asyncio.to_thread(network_store.remove, nid):
        raise HTTPException(404, i18n.t("networks.error.not_found"))
    logger.info("Rete tolta: %s", nid)
    return await asyncio.to_thread(_state, cidr, own)


def _written(nid: str, cidr: str) -> model.Network:
    """A network the person wrote and that fits now, or the main network (its devices only: networks.purge); 404 for an unknown one."""
    main = registry.main_network(cidr)
    network = main if nid == registry.MAIN_ID else next((n for n in network_store.load(main) if n.id == nid), None)
    if network is None:
        raise HTTPException(404, i18n.t("networks.error.not_found"))
    return network


@router.get("/api/networks/{nid}/purge")
async def api_networks_purge_preview(nid: str, request: Request):
    i18n.use_request(request)
    cidr, _own = await registry.main()
    network = await asyncio.to_thread(_written, nid, cidr)
    return await asyncio.to_thread(purge.preview, network)


@router.post("/api/networks/{nid}/purge")
async def api_networks_purge(nid: str, request: Request):
    i18n.use_request(request)
    cidr, own = await registry.main()
    network = await asyncio.to_thread(_written, nid, cidr)
    gone = await asyncio.to_thread(purge.run, network)
    for device_id in gone:
        state.remove(device_id)
    logger.info("Rete eliminata da zero: %s (%d schede)", network.cidr, len(gone))
    return await asyncio.to_thread(_state, cidr, own)
