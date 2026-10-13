"""API of the ignored devices."""
import asyncio

from fastapi import APIRouter, HTTPException, Request

from ..scan import dhcp, mdns_listener
from ..storage import blocklist, journal, newdevices
from ..storage.history import history
from .. import i18n
from .bodies import json_dict
from ..applog import logger

router = APIRouter()


async def _json(request: Request) -> dict:
    return await json_dict(request, "ignored.error.invalid")


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
    journal.add("normal", "journal.unignored", icon="eye-off", name=item_id)
    return {"items": await asyncio.to_thread(blocklist.list_items)}


def _forget_mac(mac: str) -> bool:
    """Forget what the app remembers about a MAC: the known-MAC row (if it is an ignored one), the DHCP name and the Bonjour card.
    True if there was something to forget."""
    mac = (newdevices.normalize_mac(mac) or "").upper()
    if not mac:
        return False
    row = history.known_all().get(mac)
    found = _drop_ignored_row(mac, row)
    low = mac.lower()
    ip = (mdns_listener.by_mac.get(low) or {}).get("ip") or (row or {}).get("ip")
    if _drop_dhcp_name(low):
        found = True
    if _drop_bonjour_card(low, ip):
        found = True
    return found


def _drop_ignored_row(mac: str, row: dict | None) -> bool:
    """Delete the known-MAC row when it is an ignored one. True if it was deleted."""
    if row and row["status"] == "ignored":
        history.known_delete(mac)
        return True
    return False


def _drop_dhcp_name(low_mac: str) -> bool:
    """Forget the DHCP name seen for a (lowercase) MAC. True if there was one."""
    if dhcp.seen.pop(low_mac, None) is None:
        return False
    dhcp._save()
    return True


def _drop_bonjour_card(low_mac: str, ip: str | None) -> bool:
    """Forget the Bonjour card of a (lowercase) MAC and of its IP. True if one of the two existed."""
    changed = mdns_listener.by_mac.pop(low_mac, None) is not None
    if ip and mdns_listener.by_ip.pop(ip, None) is not None:
        changed = True
    if changed:
        mdns_listener._save()
    return changed


@router.post("/api/ignored/forget")
async def api_ignored_forget(request: Request):
    """Forget an ignored device: it leaves the list and what the app remembers about it goes too.
    Body {"id": item id} for a device ignored from a search, or {"mac": ...} for one found on the network."""
    body = await _json(request)
    if isinstance(body.get("id"), str):
        name, something = await _forget_listed_item(body["id"]), True      # an entry of the list is always something
    elif isinstance(body.get("mac"), str):
        name, something = await _forget_found_mac(body["mac"])
    else:
        raise HTTPException(400, i18n.t("ignored.error.invalid"))
    if something:
        logger.info("Dispositivo ignorato dimenticato: %s", name)
        journal.add("normal", "journal.forgotten", icon="eye-off", name=name)
    return {"items": await asyncio.to_thread(blocklist.list_items), "macs": await asyncio.to_thread(newdevices.list_ignored, history)}


async def _forget_listed_item(item_id: str) -> str:
    """Remove an entry of the ignore list (and what is remembered about it). Returns the name to show in the journal."""
    item = next((i for i in await asyncio.to_thread(blocklist.list_items) if i["id"] == item_id), None)
    if not item:
        raise HTTPException(404, i18n.t("ignored.error.not_found"))
    await asyncio.to_thread(blocklist.remove, item["id"])
    if item["kind"] == "mac":
        await asyncio.to_thread(_forget_mac, item["value"])
    elif item["kind"] == "ip" and mdns_listener.by_ip.pop(item["value"], None) is not None:
        await asyncio.to_thread(mdns_listener._save)
    return item["label"] or item["value"]


async def _forget_found_mac(raw_mac: str) -> tuple[str, bool]:
    """Forget a device found on the network. Returns (name for the journal, whether there was something to forget)."""
    mac = newdevices.normalize_mac(raw_mac)
    if not mac:
        raise HTTPException(400, i18n.t("ignored.error.invalid"))
    row = history.known_all().get(mac)
    name = (row or {}).get("hostname") or mac
    return name, await asyncio.to_thread(_forget_mac, mac)
