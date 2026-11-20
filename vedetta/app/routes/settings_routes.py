"""settings_routes: moved out of main.py (see tools/split_module.py)."""
from fastapi import APIRouter
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
import asyncio
from .. import i18n
from .bodies import json_dict
from ..ha import ha_notify, notify_queue
from ..scan import router_arp
from ..storage import journal, newdevices, settings, userlang
from ..applog import logger
from ..state import state


router = APIRouter()


@router.post("/api/lang/{code}")
async def api_set_lang(code: str, request: Request):
    """The language chosen in the menu. "auto" gives the choice back to the automatic one (the language of Home Assistant). The choice is
    kept on the server for the logged-in Home Assistant user (it follows them to every browser) and in a cookie for the browser."""
    path = getattr(request.state, "base", "") or "/"      # cookie path = ingress prefix (empty at the root -> "/", as before)
    user = request.headers.get("x-remote-user-id")
    if code == "auto":
        userlang.put(user, None)
        response = JSONResponse({"lang": "auto"})
        response.delete_cookie(i18n.COOKIE_NAME, path=path)
        return response
    if code not in dict(i18n.available()):
        raise HTTPException(404, "Unknown language")
    userlang.put(user, code)
    response = JSONResponse({"lang": code})
    response.set_cookie(i18n.COOKIE_NAME, code, max_age=i18n.COOKIE_MAX_AGE, samesite="lax", path=path)
    return response


@router.get("/api/settings")
async def api_settings_get():
    return settings.load()


@router.post("/api/settings")
async def api_settings_set(request: Request):
    body = await json_dict(request)
    try:
        before = settings.load()["poll_interval"]
        updated = settings.update(body)
        if updated["poll_interval"] != before:
            state.trigger(reason="settings")  # the new interval applies at once (at most MIN_GAP_S after the last cycle): wake the loop
        return updated
    except ValueError as exc:
        raise HTTPException(400, f"Valore non valido: {exc}")
    except OSError:
        logger.exception("Salvataggio impostazioni fallito")
        raise HTTPException(500, "Salvataggio non riuscito")


@router.get("/api/new-devices")
async def api_new_devices():
    return await asyncio.to_thread(newdevices.list_new)


@router.get("/api/new-devices/ignored")
async def api_new_devices_ignored():
    return await asyncio.to_thread(newdevices.list_ignored)


@router.post("/api/new-devices/unignore")
async def api_new_devices_unignore(request: Request):
    body = await json_dict(request)
    mac = body.get("mac")
    if not isinstance(mac, str) or not await asyncio.to_thread(newdevices.unignore, mac):
        raise HTTPException(404, "MAC non trovato tra gli ignorati")
    journal.add("normal", "journal.unignored", icon="eye-off", name=mac)
    state.set_new_devices(await asyncio.to_thread(newdevices.list_new))
    return await asyncio.to_thread(newdevices.list_ignored)


@router.post("/api/new-devices/ignore")
async def api_new_devices_ignore(request: Request):
    try:
        body = await request.json()
    except ValueError:
        body = {}
    macs = body.get("macs") if isinstance(body, dict) else None
    if macs is not None and not isinstance(macs, list):
        raise HTTPException(400, "Elenco MAC non valido")
    devices = await asyncio.to_thread(newdevices.ignore, [str(m) for m in macs or []])
    logger.info("Nuovi dispositivi ignorati: %s", ", ".join(map(str, macs)) if macs else "tutti")
    state.set_new_devices(devices)
    return devices


@router.get("/api/sentinel")
async def api_sentinel_get():
    """The Sentinel's way out: {"ha_events", "notify_order"} ("notify_service" is always empty: the single service of 0.99.x)."""
    return settings.sentinel_load()


@router.post("/api/sentinel")
async def api_sentinel_set(request: Request):
    return _update_or_error(settings.sentinel_update, await json_dict(request))


@router.get("/api/sentinel/services")
async def api_sentinel_services():
    """The notify services of Home Assistant ([] outside Home Assistant), the messages waiting in line and the last answer of each."""
    return {"services": await ha_notify.notify_services(), **notify_queue.status()}


@router.post("/api/sentinel/test")
async def api_sentinel_test(request: Request):
    """«Send a test» (no service: an event and a test message in line for the whole order) or the «Try» of one recipient."""
    body = await json_dict(request)
    service = body.get("service")
    if service is not None and not settings.sentinel_valid("notify_service", service):
        raise HTTPException(400, "Valore non valido: service")
    return await ha_notify.test(service)


@router.get("/api/snmp")
async def api_snmp_get():
    """The ARP table of the router through SNMP: its address, whether a community is written (never the community), the last reading."""
    return router_arp.status()


@router.post("/api/snmp")
async def api_snmp_set(request: Request):
    _update_or_error(settings.snmp_update, await json_dict(request))
    return router_arp.status()


def _update_or_error(update, body: dict) -> dict:
    """One group of settings saved: a wrong value is a 400, a file that cannot be written the same clean 500 as /api/settings."""
    try:
        return update(body)
    except ValueError as exc:
        raise HTTPException(400, f"Valore non valido: {exc}")
    except OSError:
        logger.exception("Salvataggio impostazioni fallito")
        raise HTTPException(500, "Salvataggio non riuscito")


@router.post("/api/snmp/test")
async def api_snmp_test():
    """«Try»: one reading of the router's table now (how many addresses, or why not)."""
    return await router_arp.test()

