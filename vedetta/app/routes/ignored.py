"""API of the ignored devices."""
import asyncio

from fastapi import APIRouter, HTTPException, Request

from ..scan import dhcp, mdns_listener
from ..storage import blocklist, journal, newdevices
from ..storage.history import history
from .. import i18n
from ..applog import logger

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
    """Ignore devices found by a search: body {"hosts":[{ip, mac, hostname}]}."""
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
    from ..storage import journal  # late import
    journal.add("normal", "journal.unignored", icon="eye-off", name=item_id)
    return {"items": await asyncio.to_thread(blocklist.list_items)}


def _forget_mac(mac: str) -> None:
    """Forget what the app remembers about a MAC: the known-MAC row (if it is an ignored one), the DHCP name and the Bonjour card."""
    mac = (newdevices.normalize_mac(mac) or "").upper()
    if not mac:
        return
    row = history.known_all().get(mac)
    if row and row["status"] == "ignored":
        history.known_delete(mac)
    low = mac.lower()
    ip = (mdns_listener.by_mac.get(low) or {}).get("ip") or (row or {}).get("ip")
    if dhcp.seen.pop(low, None) is not None:
        dhcp._save()
    changed = mdns_listener.by_mac.pop(low, None) is not None
    if ip and mdns_listener.by_ip.pop(ip, None) is not None:
        changed = True
    if changed:
        mdns_listener._save()


@router.post("/api/ignored/forget")
async def api_ignored_forget(request: Request):
    """Forget an ignored device: it leaves the list and what the app remembers about it goes too.
    Body {"id": item id} for a device ignored from a search, or {"mac": ...} for one found on the network."""
    body = await _json(request)
    name = ""
    if isinstance(body.get("id"), str):
        item = next((i for i in await asyncio.to_thread(blocklist.list_items) if i["id"] == body["id"]), None)
        if not item:
            raise HTTPException(404, i18n.t("ignored.error.not_found"))
        await asyncio.to_thread(blocklist.remove, item["id"])
        name = item["label"] or item["value"]
        if item["kind"] == "mac":
            await asyncio.to_thread(_forget_mac, item["value"])
        elif item["kind"] == "ip" and mdns_listener.by_ip.pop(item["value"], None) is not None:
            await asyncio.to_thread(mdns_listener._save)
    elif isinstance(body.get("mac"), str):
        mac = newdevices.normalize_mac(body["mac"])
        if not mac:
            raise HTTPException(400, i18n.t("ignored.error.invalid"))
        row = history.known_all().get(mac)
        name = (row or {}).get("hostname") or mac
        await asyncio.to_thread(_forget_mac, mac)
    else:
        raise HTTPException(400, i18n.t("ignored.error.invalid"))
    logger.info("Dispositivo ignorato dimenticato: %s", name)
    journal.add("normal", "journal.forgotten", icon="eye-off", name=name)
    return {"items": await asyncio.to_thread(blocklist.list_items), "macs": await asyncio.to_thread(newdevices.list_ignored, history)}
