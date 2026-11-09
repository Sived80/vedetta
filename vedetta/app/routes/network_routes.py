"""The networks API, for the panel «Networks»: the main network (read from the host, never written) and the networks written by the person, with
how many cards each holds; add, change (touch, state, excluded ranges) and remove. A network that does not fit gets a 400 with the translated
reason (networks.model codes). Removing a network that still holds cards brings it back as "proposed" at the next cycle (K12): its cards are
removed from the list of devices, not here. Nothing here touches a device: the cycle and the searches read the networks through networks.registry."""
import asyncio

from fastapi import APIRouter, HTTPException, Request

from .. import i18n
from ..applog import logger
from ..networks import model, registry
from ..storage import devices_config, network_store
from .bodies import json_dict

router = APIRouter()


def _row(network: model.Network, cards: list, fits: bool) -> dict:
    return {"id": network.id, "cidr": str(network.cidr), "via": sorted(network.via), "touch": network.touch, "state": network.state,
            "cards": sum(1 for ip in cards if registry.holds(network, ip)), "fits": fits}


def _state(cidr: str) -> dict:
    main = registry.main_network(cidr)
    cards = [d.get("ip") for d in devices_config.load_devices()]
    fitting = network_store.load(main)
    fit_ids = {n.id for n in fitting}
    return {"main": _row(main, cards, True), "networks": [_row(n, cards, n.id in fit_ids) for n in fitting],
            "left_out": [r.get("id") for r in network_store.rows() if r.get("id") not in fit_ids],
            "limits": {"max_networks": model.MAX_NETWORKS, "widest": model.WIDEST, "widest_other": model.WIDEST_OTHER}}


def _refused(exc: model.Rejected) -> HTTPException:
    return HTTPException(400, {"code": exc.code, "message": i18n.t(f"networks.error.{exc.code}")})


@router.get("/api/networks")
async def api_networks(request: Request):
    i18n.use_request(request)
    cidr, _ = await registry.main()
    return await asyncio.to_thread(_state, cidr)


@router.post("/api/networks")
async def api_networks_add(request: Request):
    body = await json_dict(request)
    cidr, _ = await registry.main()
    try:
        network = await asyncio.to_thread(network_store.add, body, registry.main_network(cidr))
    except model.Rejected as exc:
        raise _refused(exc)
    logger.info("Rete aggiunta: %s (%s, %s)", network.cidr, ",".join(sorted(network.via)), network.state)
    return await asyncio.to_thread(_state, cidr)


@router.post("/api/networks/{nid}")
async def api_networks_change(nid: str, request: Request):
    body = await json_dict(request)
    cidr, _ = await registry.main()
    try:
        network = await asyncio.to_thread(network_store.change, nid, body, registry.main_network(cidr))
    except model.Rejected as exc:
        raise _refused(exc)
    if network is None:
        raise HTTPException(404, i18n.t("networks.error.not_found"))
    logger.info("Rete cambiata: %s (%s, %s)", network.cidr, network.touch, network.state)
    return await asyncio.to_thread(_state, cidr)


@router.delete("/api/networks/{nid}")
async def api_networks_remove(nid: str, request: Request):
    i18n.use_request(request)
    cidr, _ = await registry.main()
    if not await asyncio.to_thread(network_store.remove, nid):
        raise HTTPException(404, i18n.t("networks.error.not_found"))
    logger.info("Rete tolta: %s", nid)
    return await asyncio.to_thread(_state, cidr)
