"""device_routes: moved out of main.py (see tools/split_module.py)."""
from fastapi import APIRouter
from fastapi import HTTPException, Request
from ..routes.scan_routes import SCAN_INFO_KEYS
from ..sse import SSE_HEADERS, _sse
from fastapi.responses import StreamingResponse
import asyncio
from ..storage import blocklist, devices_config, journal
from ..netutil import filter_local_ips, get_local_network
from ..ha import ha_data
from ..storage.history import history
from .. import i18n
import ipaddress
from ..applog import logger
from ..ha.mqtt_ha import service as mqtt_service
from ..recognition import naming
from ..scan import pipeline, touch_policy
from ..scan.rescan import rescan_device
from ..scan import scan_common, scanner, wol
from .bodies import json_dict
from ..state import state
import time


router = APIRouter()


@router.post("/api/devices/add")
async def api_devices_add(request: Request):
    body = await json_dict(request)
    to_add = [e for e in map(_new_device_entry, body.get("devices", [])) if e is not None]
    try:
        added = devices_config.add_devices(to_add)
    except Exception:
        logger.exception("Errore aggiungendo dispositivi: %s", [c.get("ip") for c in to_add])
        raise HTTPException(500, "Salvataggio non riuscito")
    if added:
        await _settle_added(added)
    return {"added": added}


def _new_device_entry(c: dict) -> dict | None:
    """The entry to add for one candidate of the search: only the allowed fields, cleaned; None if its address is not valid."""
    if not scanner.is_valid_ipv4(c.get("ip", "")):
        return None
    entry = {"ip": c["ip"], "adapter": c.get("adapter") if c.get("adapter") in ("shelly_gen1", "generic") else "generic"}
    if c.get("name"):
        entry["name"] = str(c["name"])[:80]
    if c.get("name_source") in ("user", *naming.PRIORITY):
        entry["name_source"] = c["name_source"]
    port = scan_common.valid_port(c.get("port"))     # a bad or no-talk port is left out: the default stays
    if port:
        entry["port"] = port
    keep = _kept_scan_info(c.get("scan_info"))
    if keep:
        entry["scan_info"] = keep
    return entry


def _kept_scan_info(info) -> dict:
    """What the search has already learned about the device (server and web title): short texts for these keys, and whether the device is slow (a
    boolean: the next search skips the all-ports pilot test, which takes 14-16 s on a small device)."""
    if not isinstance(info, dict):
        return {}
    kept = {k: str(info[k])[:200] for k in SCAN_INFO_KEYS if info.get(k)}
    if info.get("slow_scan"):
        kept["slow_scan"] = True
    if ports := _kept_ports(info.get("ports")):
        kept["ports"] = ports
    return kept


_PORT_CATEGORIES = {"media", "print", "vpn", "mail", "web", "remote", "iot", "infra", "file", "db", "other"}   # as scan_format writes them
_MAX_KEPT_PORTS = 100


def _kept_ports(ports) -> list[dict]:
    """The ports the search saw, in the shape scan_format writes them (the list comes back from the page: only a port number, a short label and booleans are taken, a bad entry is dropped).
    `scanned_at` is not kept with them: it means that the deep search read the ports and services, and that search still runs."""
    if not isinstance(ports, list):
        return []
    kept = []
    for p in ports:
        if not isinstance(p, dict) or scan_common.port_number(p) is None:
            continue
        item = {"label": str(p["label"])[:80], "confirmed": bool(p.get("confirmed")), "category": p.get("category") if p.get("category") in _PORT_CATEGORIES else "other"}
        if "web_ui" in p:
            item.update(web_ui=bool(p["web_ui"]), web_scheme="https" if p.get("web_scheme") == "https" else "http")
        kept.append(item)
        if len(kept) == _MAX_KEPT_PORTS:
            break
    return kept


async def _settle_added(added: list[dict]) -> None:
    """The new cards: log, journal, read each one at once and tell the new-devices watch (a just-added 'new' MAC becomes 'known')."""
    logger.info("Aggiunti %d dispositivi: %s", len(added), ", ".join(d["ip"] for d in added))
    for d in added:
        journal.add("normal", "journal.added", icon="plus-circle", name=d.get("name") or d["ip"], ip=d["ip"])
    await asyncio.gather(*(state.refresh_device(d["id"]) for d in added))
    await state.check_new_devices()


@router.post("/api/devices/{device_id}/wake")
async def api_device_wake(device_id: str):
    """Wake-on-LAN: magic packet in broadcast (ports 9 and 7)."""
    device = next((d for d in devices_config.load_devices() if d["id"] == device_id), None)
    if device is None:
        raise HTTPException(404, "Dispositivo non trovato")
    mac = await _wake_mac(device_id, device)
    if not wol.is_valid_mac(mac):
        raise HTTPException(400, i18n.t("error.no_mac"))
    sent = await asyncio.to_thread(wol.send, mac, await _broadcast_targets())
    if not sent:
        raise HTTPException(500, "Invio non riuscito")
    logger.info("Wake-on-LAN inviato a %s (%s)", device.get("name") or device["ip"], mac)
    # The packet gets no reply: we check whether the device turns on within 2 minutes and, if so,
    # we remember that wake-up works (wol_ok), so the button stays offered for that device.
    asyncio.create_task(_watch_wake(device_id))
    return {"sent": True}


async def _wake_mac(device_id: str, device: dict) -> str | None:
    """The MAC to wake. A powered-off device no longer shows it to the probe: fall back to the last MAC seen in the history, then to the one known for its IP."""
    mac = (state.devices.get(device_id) or {}).get("mac") or device.get("mac")
    if not wol.is_valid_mac(mac):
        mac = await asyncio.to_thread(history.last_mac, device_id)
    if not wol.is_valid_mac(mac):
        known = await asyncio.to_thread(history.known_all)
        mac = next((m for m, r in known.items() if r["ip"] == device["ip"]), None)
    return mac


async def _broadcast_targets() -> list[str]:
    targets = ["255.255.255.255"]
    try:
        subnet, _ = await get_local_network()
        targets.append(str(ipaddress.ip_network(subnet).broadcast_address))
    except Exception:
        pass
    return targets


async def _watch_wake(device_id: str) -> None:
    try:
        for _ in range(24):
            await asyncio.sleep(5)
            if (state.devices.get(device_id) or {}).get("online"):
                await asyncio.to_thread(devices_config.set_override, device_id, "wol_ok", "1")
                logger.info("Wake-on-LAN riuscito su %s: sveglia ricordata", device_id)
                return
    except Exception:
        logger.exception("Controllo della sveglia fallito per %s", device_id)


@router.post("/api/devices/{device_id}/rename")
async def api_device_rename(device_id: str, request: Request):
    body = await json_dict(request)
    name = str(body.get("name", "")).strip()[:80]
    if not name:
        raise HTTPException(400, i18n.t("error.invalid_name"))
    port = body.get("port")
    if port is not None:
        port = scan_common.valid_port(port)
        if port is None:
            raise HTTPException(400, i18n.t("error.invalid_port"))
    # mobile: true/false = explicit user choice, absent/null = goes back
    # to being decided by the name (see probe.py).
    mobile = body.get("mobile")
    mobile = bool(mobile) if isinstance(mobile, bool) else None
    try:
        updated = devices_config.update_device(device_id, name, port, mobile)
    except Exception:
        logger.exception("Errore rinominando %s", device_id)
        raise HTTPException(500, "Salvataggio non riuscito")
    if not updated:
        raise HTTPException(404, "Dispositivo non trovato")
    logger.info("Rinominato %s -> \"%s\" (porta %s)", device_id, name, updated.get("port"))
    await state.refresh_device(device_id)
    return updated


_bg_tasks: set = set()


@router.post("/api/devices/{device_id}/override")
async def api_device_override(device_id: str, request: Request):
    """Brand and/or type chosen by hand ("brand", "type"); null = back to automatic."""
    body = await json_dict(request)
    updated = None
    if "ha_share" in body:   # share with Home Assistant (true) or remove from HA (false)
        updated = devices_config.set_override(device_id, "ha_share", "1" if body["ha_share"] is True else None) or updated
        mqtt_service.refresh()
    if "focus" in body:
        updated = _set_focus(device_id, body) or updated
    updated = _set_brand_type(device_id, body) or updated
    if not updated:
        raise HTTPException(404, "Dispositivo non trovato")
    logger.info("Scelta manuale su %s: %s", device_id, {k: body[k] for k in ("brand", "type", "ha_share", "focus") if k in body})
    # The device is read again behind the answer (a probe over the network takes seconds): the page already shows the choice,
    # and the card is sent again to it (event) as soon as the reading is done.
    _bg(state.refresh_device(device_id))
    return {"ok": True}


def _bg(coro) -> None:
    """Runs a coroutine behind the answer, keeping it alive and logging its failure."""
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)

    def done(t):
        _bg_tasks.discard(t)
        if not t.cancelled() and t.exception():
            logger.error("Aggiornamento in secondo piano non riuscito: %s", t.exception())
    task.add_done_callback(done)


def _set_focus(device_id: str, body: dict):
    """"Device under examination": its card, history and a note go in the export for analysis. Returns what set_override returned (truthy = found)."""
    if body["focus"] is not True:
        updated = devices_config.set_override(device_id, "focus", None)
        devices_config.set_override(device_id, "focus_note", None)
        return updated
    others = [d for d in devices_config.load_devices() if d.get("focus") and d["id"] != device_id]
    if len(others) >= devices_config.FOCUS_MAX:
        raise HTTPException(409, "Troppi dispositivi segnalati")
    note = str(body.get("focus_note") or "").strip()[:devices_config.FOCUS_NOTE_MAX] or None
    updated = devices_config.set_override(device_id, "focus", "1")
    devices_config.set_override(device_id, "focus_note", note)
    return updated


def _set_brand_type(device_id: str, body: dict):
    """Brand and/or type chosen by hand; empty = back to automatic. Returns True when the device was found by any of the changes."""
    updated = None
    for key, field in (("brand", "brand_user"), ("type", "type_user")):
        if key not in body:
            continue
        value = body[key]
        value = str(value).strip()[:40] if value else None
        if key == "type" and value and value not in ha_data.TYPE_ORDER + ("generic",):
            raise HTTPException(400, "Tipo non valido")
        updated = devices_config.set_override(device_id, field, value) or updated
    return updated


@router.delete("/api/devices/{device_id}")
async def api_device_delete(device_id: str, ignore: bool = False):
    gone = state.devices.get(device_id) or {}
    if ignore:
        await _remember_ignored(device_id)
    try:
        removed = devices_config.remove_device(device_id)
    except Exception:
        logger.exception("Errore eliminando %s", device_id)
        raise HTTPException(500, "Eliminazione non riuscita")
    if not removed:
        raise HTTPException(404, "Dispositivo non trovato")
    logger.info("Eliminato %s", device_id)
    journal.add("normal", "journal.ignored" if ignore else "journal.removed", icon="eye-off" if ignore else "close-circle",
                name=gone.get("name") or gone.get("ip") or device_id, ip=gone.get("ip") or "-")
    state.remove(device_id)
    return {"ok": True}


async def _remember_ignored(device_id: str) -> None:
    """Before deleting it: what we know about the device is needed to recognize it later."""
    known = state.devices.get(device_id) or {}
    name = None if known.get("name") == known.get("ip") else known.get("name")
    mac = known.get("mac") or state._last_mac.get(device_id)
    if known.get("ip"):
        await asyncio.to_thread(blocklist.add_host, known["ip"], mac, name, f"{known.get('name') or known['ip']} · {known['ip']}")


@router.post("/api/devices/rescan")
async def api_devices_rescan(request: Request):
    """Re-run a deep scan (services, web page title) on the
    devices chosen by the user. Slow on purpose: it must be launched by hand,
    not on every automatic refresh. Streaming (SSE): one event per completed
    device, to show the real progress in the pop-up."""
    body = await json_dict(request)
    ids = set(body.get("ids", []))
    devices = await _local_devices_of(ids)
    logger.info("Scansione approfondita avviata su %d dispositivi: %s", len(devices), ", ".join(d["ip"] for d in devices))
    state.rescan_started([d["id"] for d in devices])
    batch = await _prepare_batch_or_release(devices)
    tasks = _start_rescans(devices, batch)
    return StreamingResponse(_rescan_stream(devices, tasks), media_type="text/event-stream", headers=SSE_HEADERS)


async def _local_devices_of(ids: set) -> list[dict]:
    """The chosen devices that are on the local network."""
    devices = [d for d in devices_config.load_devices() if d["id"] in ids]
    local_ips = set(await filter_local_ips([d["ip"] for d in devices]))
    return [d for d in devices if d["ip"] in local_ips]


async def _prepare_batch_or_release(devices: list[dict]):
    """The deep profile's batch functions (mDNS, SSDP: a single broadcast for the whole LAN) must be run only once, not repeated for every device."""
    try:
        return await pipeline.prepare_batch("deep", [d["ip"] for d in touch_policy.touchable(devices)])
    except Exception:
        for d in devices:
            state.rescan_finished(d["id"])
        raise


def _start_rescans(devices: list[dict], batch) -> list:
    """One task per device. They are created here and not in the generator: if the browser changes page the stream is interrupted but the scans carry on to the end."""
    async def rescan_one(d: dict) -> dict:
        try:
            await rescan_device(d, batch)
        except Exception:
            logger.exception("%s (%s) scansione fallita", d["ip"], d.get("name") or d["ip"])
        finally:
            state.rescan_finished(d["id"])
        return d

    tasks = [asyncio.create_task(rescan_one(d)) for d in devices]
    for task in tasks:
        state.track(task)
    return tasks


async def _rescan_stream(devices: list[dict], tasks: list):
    total = len(devices)
    yield _sse({"type": "total", "total": total})
    done = 0
    for task in asyncio.as_completed(tasks):
        d = await task
        done += 1
        yield _sse({"type": "progress", "done": done, "total": total, "name": d.get("name") or d["ip"], "id": d["id"]})
    logger.info("Scansione approfondita completata (%d dispositivi)", total)
    yield _sse({"type": "complete", "rescanned": total})


@router.get("/api/devices/{device_id}/presence")
async def api_device_presence(device_id: str):
    device = state.devices.get(device_id)
    if device is None:
        raise HTTPException(404, "Dispositivo non trovato")
    now = time.time()
    day, week = await asyncio.gather(
        asyncio.to_thread(history.presence_segments, device_id, now - 86400, now),
        asyncio.to_thread(history.presence_segments, device_id, now - 7 * 86400, now),
    )
    return {
        "name": device["name"],
        "online": device["online"],
        "last_seen": device.get("last_seen"),
        "windows": {"24h": day, "7d": week},
    }
