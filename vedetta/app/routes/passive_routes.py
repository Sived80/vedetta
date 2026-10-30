"""Routes of the devices that Home Assistant sees ("Networks seen by Home Assistant"): the switch, the reading, the list to choose from, the adoption, and the changes to an adopted device.

The changes of an adopted device (name, type, brand, removal) arrive on the routes of the other devices (/api/devices/{id}/rename, /override, DELETE): those routes hand the ids that start with "ha-" to
the functions at the end of this file."""
import asyncio
import time

from fastapi import APIRouter, HTTPException, Request

from .. import i18n
from ..ha import ha_data, ha_registry, passive_service, passive_view
from ..state import state
from ..storage import passive_store
from .bodies import json_dict

router = APIRouter()
NAME_MAX = 80
BRAND_MAX = 40


def _known() -> tuple[set, set]:
    """MACs (uppercase) and addresses of the devices Vedetta already has: they are not offered again."""
    macs = {str(d.get("mac") or "").upper() for d in state.devices.values()} | {str(m).upper() for m in state._last_mac.values()}
    return {m for m in macs if m}, {d.get("ip") for d in state.devices.values() if d.get("ip")}


def payload(data: dict) -> dict:
    macs, ips = _known()
    return {"enabled": bool(data["enabled"]), "available": bool(ha_registry.token()), "read_at": data["read_at"], "error": data["error"],
            "adopted": len(data["adopted"]), "candidates": passive_view.candidates(data, macs, ips)}


@router.get("/api/ha/networks")
async def api_networks(request: Request):
    i18n.use_request(request)
    return payload(await asyncio.to_thread(passive_store.snapshot))


@router.post("/api/ha/networks/enabled")
async def api_networks_enabled(request: Request):
    """Turns the function on or off. Off: nothing is read any more; what was adopted stays, with its last known state."""
    body = await json_dict(request)
    if not isinstance(body.get("enabled"), bool):
        raise HTTPException(400, "enabled must be true or false")
    await asyncio.to_thread(passive_store.set_enabled, body["enabled"])
    return payload(await asyncio.to_thread(passive_store.snapshot))


@router.post("/api/ha/networks/read")
async def api_networks_read():
    """Reads Home Assistant now. Only when the function is on."""
    if not await asyncio.to_thread(passive_store.enabled):
        raise HTTPException(409, "The function is off")
    return payload(await passive_service.read_now())


@router.post("/api/ha/networks/adopt")
async def api_networks_adopt(request: Request):
    """Adopts the chosen clients ({"macs": [...]}): they become cards of the page, in the groups of their type."""
    body = await json_dict(request)
    macs = body.get("macs")
    if not isinstance(macs, list) or not all(isinstance(m, str) for m in macs):
        raise HTTPException(400, "macs must be a list")
    done = await asyncio.to_thread(passive_store.adopt, [ha_registry.norm_mac(m) for m in macs if ha_registry.norm_mac(m)], time.time())
    if done:
        await passive_service.read_now()          # the presence of the new cards is written at once
    return {**payload(await asyncio.to_thread(passive_store.snapshot)), "done": len(done)}


# ---- the changes of an adopted device: the same addresses as the other devices (/api/devices/ha-<mac>/...), taken before them ----
def _mac_or_404(mac: str) -> str:
    """The MAC (with colons) of an adopted device from the twelve hexadecimal digits of its id."""
    found = passive_store.mac_of(passive_store.ID_PREFIX + mac)
    if not found or found not in passive_store.snapshot()["adopted"]:
        raise HTTPException(404, "Dispositivo non trovato")
    return found


def _changed() -> dict:
    state.emit_event({"type": "passive"})      # the open pages read the devices again
    return {"ok": True}


@router.post("/api/devices/ha-{mac}/rename")
async def api_passive_rename(mac: str, request: Request):
    body = await json_dict(request)
    name = str(body.get("name", "")).strip()[:NAME_MAX]
    if not name:
        raise HTTPException(400, i18n.t("error.invalid_name"))
    passive_store.set_edit(_mac_or_404(mac), "name", name)       # whether it is a phone is not asked: nothing is probed
    return _changed()


@router.post("/api/devices/ha-{mac}/override")
async def api_passive_override(mac: str, request: Request):
    """Brand and type chosen by hand (empty = back to what Home Assistant says). The flag and the sharing do not exist for these devices."""
    body = await json_dict(request)
    found = _mac_or_404(mac)
    for key in ("brand", "type"):
        if key in body:
            _set_choice(found, key, body[key])
    return _changed()


def _set_choice(mac: str, key: str, raw) -> None:
    value = str(raw).strip() if raw else None
    if key == "type" and value and value not in ha_data.TYPE_ORDER + ("generic",):
        raise HTTPException(400, "Tipo non valido")
    passive_store.set_edit(mac, key, value[:BRAND_MAX] if value else None)


@router.delete("/api/devices/ha-{mac}")
async def api_passive_remove(mac: str):
    """Takes the device off the page: it is offered again in the list as long as Home Assistant sees it."""
    passive_store.forget(_mac_or_404(mac))
    return _changed()
