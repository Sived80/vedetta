"""API dei dispositivi ignorati."""
import asyncio

from fastapi import APIRouter, HTTPException, Request

from . import blocklist, i18n
from .applog import logger

router = APIRouter()


async def _json(request: Request) -> dict:
    i18n.use_request(request)
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise HTTPException(400, i18n.t("ignored.error.invalid"))
    return body


@router.get("/api/ignored")
async def api_ignored():
    return {"items": await asyncio.to_thread(blocklist.list_items)}


@router.post("/api/ignored")
async def api_ignored_add(request: Request):
    body = await _json(request)
    try:
        items = await asyncio.to_thread(blocklist.add, str(body.get("kind", "")), str(body.get("value", "")), str(body.get("label", "")))
    except ValueError:
        raise HTTPException(400, i18n.t("ignored.error.invalid"))
    logger.info("Dispositivo ignorato: %s %s", body.get("kind"), body.get("value"))
    return {"items": items}


@router.post("/api/ignored/hosts")
async def api_ignored_hosts(request: Request):
    """Ignora dispositivi trovati da una ricerca: body {"hosts":[{ip, mac, hostname}]}."""
    body = await _json(request)
    items = await asyncio.to_thread(blocklist.list_items)
    for h in body.get("hosts", []) if isinstance(body.get("hosts"), list) else []:
        if isinstance(h, dict):
            items = await asyncio.to_thread(
                blocklist.add_host, h.get("ip"), h.get("mac"), h.get("hostname"),
            )
            logger.info("Dispositivo ignorato dalla ricerca: %s %s", h.get("ip"), h.get("mac") or "")
    return {"items": items}


@router.delete("/api/ignored/{item_id}")
async def api_ignored_remove(item_id: str, request: Request):
    i18n.use_request(request)
    if not await asyncio.to_thread(blocklist.remove, item_id):
        raise HTTPException(404, i18n.t("ignored.error.not_found"))
    logger.info("Dispositivo ignorato ripristinato: %s", item_id)
    from . import journal  # tardivo
    journal.add("normal", "journal.unignored", icon="eye-off", name=item_id)
    return {"items": await asyncio.to_thread(blocklist.list_items)}
