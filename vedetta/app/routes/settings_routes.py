"""settings_routes: moved out of main.py (see tools/split_module.py)."""
from fastapi import APIRouter
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
import asyncio
from .. import i18n
from .bodies import json_dict
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
