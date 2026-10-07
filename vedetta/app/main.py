import asyncio
import ipaddress
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import blocklist, ha_registry, ha_tz, mdns_listener, devices_config, dhcp, i18n, journal, roles, naming, newdevices, scanner, settings, wol
from .applog import logger
from .history import history
from .ingress import IngressMiddleware, template_context
from .maintenance import nightly_loop
from .netutil import filter_local_ips, get_local_network
from .rescan import rescan_device
from . import ha_data, pipeline, routes_flows
from . import routes_brands, routes_ignored, routes_ha, routes_mqtt
from .mqtt_ha import service as mqtt_service
from .state import state

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_: FastAPI):
    await state.load_history()
    state.start()
    asyncio.create_task(ha_tz.refresh(force=True))   # the user's time zone, from Home Assistant
    nightly = asyncio.create_task(nightly_loop())
    dhcp_transport = await dhcp.start()
    ha_registry.start()  # Home Assistant registry (read-only; empty outside HA)
    mdns_listener.start(state)  # Bonjour names: memory and continuous listening
    await mqtt_service.start(state)  # MQTT publishing towards HA (off if not configured)
    roles.start(state, on_change=state.emit_event, on_alert=state.emit_alert)  # who does what: gateway, DHCP, DNS, repeaters
    logger.info("Servizio avviato")
    yield
    if dhcp_transport:
        dhcp_transport.close()
    nightly.cancel()
    await ha_registry.stop()
    await mdns_listener.stop()
    await roles.stop()
    await mqtt_service.stop()
    await state.stop()


app = FastAPI(title="Vedetta", lifespan=lifespan)
app.include_router(routes_brands.router)
app.include_router(routes_ignored.router)
app.include_router(routes_flows.router)
app.include_router(routes_ha.router)
app.include_router(routes_mqtt.router)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.add_middleware(IngressMiddleware)  # ingress prefix -> request.state.base; optional 403 outside the Supervisor
templates = Jinja2Templates(directory=BASE_DIR / "templates", context_processors=[template_context])  # `base` in the templates


def static_version(rel_path: str) -> str:
    """Modification date of the static file, to append as ?v= in the URL: the
    browser treats every different value as a different resource, so after a
    deploy it always downloads the new version instead of serving the old
    one from cache - this avoids having to explain "do a hard refresh" after every change
    to style.css (happened several times in this very session)."""
    try:
        return str(int((BASE_DIR / "static" / rel_path).stat().st_mtime))
    except OSError:
        return "0"


templates.env.globals["static_version"] = static_version




templates.env.globals["t"] = i18n.t
templates.env.globals["t_or"] = i18n.t_or







@app.get("/")
async def root(request: Request):
    """The page is /ha (ingress_entry): the root redirects there."""
    return RedirectResponse((getattr(request.state, "base", "") or "") + "/ha")


@app.get("/healthz")
async def healthz():
    """Health check for the Supervisor watchdog: it answers only if the service is alive."""
    return {"ok": True}


@app.post("/api/lang/{code}")
async def api_set_lang(code: str, request: Request):
    if code not in dict(i18n.available()):
        raise HTTPException(404, "Unknown language")
    response = JSONResponse({"lang": code})
    # cookie path = ingress prefix (empty at the root -> "/", as before)
    response.set_cookie(i18n.COOKIE_NAME, code, max_age=i18n.COOKIE_MAX_AGE, samesite="lax",
                        path=getattr(request.state, "base", "") or "/")
    return response






@app.post("/api/refresh")
async def api_refresh():
    state.trigger(force=True)
    return {"ok": True}


@app.post("/api/pause")
async def api_pause(request: Request):
    """Pause the periodic check: {"minutes": N}; 0 = until resumed."""
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(400, "JSON non valido")
    minutes = body.get("minutes", 0) if isinstance(body, dict) else None
    if type(minutes) is not int or not 0 <= minutes <= 7 * 24 * 60:
        raise HTTPException(400, "Valore non valido: minutes")
    state.pause(minutes)
    journal.add("normal", "journal.paused" if minutes else "journal.paused_forever", icon="power", minutes=minutes)
    return state.poll_info()


@app.delete("/api/pause")
async def api_resume():
    state.resume()
    journal.add("normal", "journal.resumed", icon="power")
    return state.poll_info()




_quick_scan: asyncio.Task | None = None


async def _run_quick_scan() -> tuple[list[dict], int]:
    state.search_started()
    try:
        known_ips = {d["ip"] for d in devices_config.load_devices()}
        hosts = await pipeline.run_initial()
        new_hosts = [
            {"ip": h["ip"], "mac": h["mac"], "hostname": h["hostname"], "already_added": False}
            for h in hosts
            if h["ip"] not in known_ips
        ]
        logger.info("Ricerca rapida: %d host visti, %d nuovi", len(hosts), len(new_hosts))
        journal.add("detail", "journal.quick", icon="magnify", seen=len(hosts), new=len(new_hosts))
        # The new-devices counter is realigned to what the search found.
        newdevices.sync_present({h["mac"] for h in hosts if h.get("mac")})
        state.set_new_devices(await asyncio.to_thread(newdevices.list_new))
        # Ignored ones are not shown; their count goes in the header.
        visible = [h for h in new_hosts if not blocklist.matches(mac=h["mac"], ip=h["ip"], name=h["hostname"])]
        return visible, len(new_hosts) - len(visible)
    finally:
        state.search_finished()


@app.post("/api/scan/quick")
async def api_scan_quick():
    """Only one search at a time: whoever requests it while one is running (even from another
    device) waits for the one already started and receives the same result."""
    global _quick_scan
    if _quick_scan is None or _quick_scan.done():
        _quick_scan = asyncio.create_task(_run_quick_scan())
    else:
        logger.info("Ricerca rapida gia' in corso: la richiesta si unisce a quella")
    # shield: if a client disconnects the search continues for the others.
    visible, ignored = await asyncio.shield(_quick_scan)
    return JSONResponse(visible, headers={"X-Ignored-Count": str(ignored)})


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


# Without these headers some browsers/proxies may buffer the response
# instead of delivering it a piece at a time, defeating the streaming.
SSE_HEADERS = {"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}


@app.post("/api/scan/deep")
async def api_scan_deep(request: Request):
    """Streaming (SSE): a 'progress' event for every device that has just finished
    being analyzed in depth, so the pop-up can show the real progress
    instead of a blind wait."""
    body = await request.json()
    ips = await filter_local_ips([ip for ip in body.get("ips", []) if scanner.is_valid_ipv4(ip)])
    hints = body.get("hints") or {}

    # The jobs start here, not inside the generator: if the browser changes page
    # the stream is interrupted but the scans continue, and the activity stays
    # flagged until they really finish.
    state.search_started()
    tasks = pipeline.start_associative(ips, hints)
    all_done = asyncio.gather(*tasks, return_exceptions=True)
    all_done.add_done_callback(lambda _: state.search_finished())
    state.track(all_done)

    async def stream():
        total = len(ips)
        yield _sse({"type": "total", "total": total})
        results = []
        done = 0
        for task in asyncio.as_completed(tasks):
            try:
                result = await task
            except asyncio.CancelledError:
                me = asyncio.current_task()
                if me is not None and getattr(me, "cancelling", lambda: 0)():
                    raise  # the stream itself is being closed, not a cancelled search
                done += 1
                continue
            except Exception:
                done += 1
                continue
            done += 1
            info = result.get("scan_info") or {}
            journal.add("detail", "journal.analyzed", icon="magnify", ip=result.get("ip", "?"),
                        ports=len(info.get("ports") or []))
            results.append(result)
            yield _sse({"type": "progress", "done": done, "total": total, "result": result})
        yield _sse({"type": "complete", "results": results})

    return StreamingResponse(stream(), media_type="text/event-stream", headers=SSE_HEADERS)


# What the search has learned about the device and that is worth keeping on adding
# (short texts): web, self-declarations (UPnP, mDNS, ONVIF, local interfaces), TLS/SSH.
SCAN_INFO_KEYS = ("http_title", "http_server", "mdns_name", "mdns_model", "mdns_manufacturer", "mdns_services",
                  "upnp_name", "upnp_manufacturer", "upnp_model", "netbios_name", "snmp_descr", "onvif_name",
                  "onvif_hardware", "onvif_manufacturer", "wsd_types", "rtsp_server", "tls_subject", "tls_issuer",
                  "ssh_hostkey", "api_source", "api_vendor", "api_model", "api_name", "api_fw", "igmp_groups")


@app.post("/api/scan/cancel")
async def api_scan_cancel(request: Request):
    """Cancel the associative searches in progress (all, or only the given IPs):
    the nmap processes are terminated, results already completed remain valid."""
    try:
        body = await request.json()
    except ValueError:
        body = {}
    ips = body.get("ips") if isinstance(body, dict) else None
    n = pipeline.cancel_associative(ips if isinstance(ips, list) else None)
    if n:
        journal.add("detail", "journal.cancelled", icon="close-circle", n=n)
    return {"cancelled": n}


@app.post("/api/devices/add")
async def api_devices_add(request: Request):
    body = await request.json()
    candidates = body.get("devices", [])
    to_add = []
    for c in candidates:
        if not scanner.is_valid_ipv4(c.get("ip", "")):
            continue
        entry = {"ip": c["ip"], "adapter": c.get("adapter") if c.get("adapter") in ("shelly_gen1", "generic") else "generic"}
        if c.get("name"):
            entry["name"] = str(c["name"])[:80]
        if c.get("name_source") in ("user", *naming.PRIORITY):
            entry["name_source"] = c["name_source"]
        if c.get("port"):
            entry["port"] = int(c["port"])
        # What the search has already learned about the device (server and web title):
        # only short texts and only these keys.
        info = c.get("scan_info")
        if isinstance(info, dict):
            keep = {k: str(info[k])[:200] for k in SCAN_INFO_KEYS if info.get(k)}
            if keep:
                entry["scan_info"] = keep
        to_add.append(entry)
    try:
        added = devices_config.add_devices(to_add)
    except Exception:
        logger.exception("Errore aggiungendo dispositivi: %s", [c.get("ip") for c in to_add])
        raise HTTPException(500, "Salvataggio non riuscito")
    if added:
        logger.info("Aggiunti %d dispositivi: %s", len(added), ", ".join(d["ip"] for d in added))
        for d in added:
            journal.add("normal", "journal.added", icon="plus-circle", name=d.get("name") or d["ip"], ip=d["ip"])
        await asyncio.gather(*(state.refresh_device(d["id"]) for d in added))
        await state.check_new_devices()  # a just-added 'new' MAC becomes 'known'
    return {"added": added}


@app.get("/api/settings")
async def api_settings_get():
    return settings.load()


@app.post("/api/settings")
async def api_settings_set(request: Request):
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(400, "JSON non valido")
    if not isinstance(body, dict):
        raise HTTPException(400, "JSON non valido")
    try:
        before = settings.load()["poll_interval"]
        updated = settings.update(body)
        if updated["poll_interval"] != before:
            state.trigger()  # the new interval applies immediately: wake the loop
        return updated
    except ValueError as exc:
        raise HTTPException(400, f"Valore non valido: {exc}")
    except OSError:
        logger.exception("Salvataggio impostazioni fallito")
        raise HTTPException(500, "Salvataggio non riuscito")


@app.get("/api/new-devices")
async def api_new_devices():
    return await asyncio.to_thread(newdevices.list_new)


@app.get("/api/new-devices/ignored")
async def api_new_devices_ignored():
    return await asyncio.to_thread(newdevices.list_ignored)


@app.post("/api/new-devices/unignore")
async def api_new_devices_unignore(request: Request):
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(400, "JSON non valido")
    mac = body.get("mac") if isinstance(body, dict) else None
    if not isinstance(mac, str) or not await asyncio.to_thread(newdevices.unignore, mac):
        raise HTTPException(404, "MAC non trovato tra gli ignorati")
    journal.add("normal", "journal.unignored", icon="eye-off", name=mac)
    state.set_new_devices(await asyncio.to_thread(newdevices.list_new))
    return await asyncio.to_thread(newdevices.list_ignored)


@app.post("/api/new-devices/ignore")
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


@app.post("/api/devices/{device_id}/wake")
async def api_device_wake(device_id: str):
    """Wake-on-LAN: magic packet in broadcast (ports 9 and 7)."""
    device = next((d for d in devices_config.load_devices() if d["id"] == device_id), None)
    if device is None:
        raise HTTPException(404, "Dispositivo non trovato")
    # A powered-off device no longer shows the MAC to the probe: fall back to the last
    # MAC seen in the history, then to the one known for its IP.
    mac = (state.devices.get(device_id) or {}).get("mac") or device.get("mac")
    if not wol.is_valid_mac(mac):
        mac = await asyncio.to_thread(history.last_mac, device_id)
    if not wol.is_valid_mac(mac):
        known = await asyncio.to_thread(history.known_all)
        mac = next((m for m, r in known.items() if r["ip"] == device["ip"]), None)
    if not wol.is_valid_mac(mac):
        raise HTTPException(400, i18n.t("error.no_mac"))
    targets = ["255.255.255.255"]
    try:
        subnet, _ = await get_local_network()
        targets.append(str(ipaddress.ip_network(subnet).broadcast_address))
    except Exception:
        pass
    sent = await asyncio.to_thread(wol.send, mac, targets)
    if not sent:
        raise HTTPException(500, "Invio non riuscito")
    logger.info("Wake-on-LAN inviato a %s (%s)", device.get("name") or device["ip"], mac)
    # The packet gets no reply: we check whether the device turns on within 2 minutes and, if so,
    # we remember that wake-up works (wol_ok), so the button stays offered for that device.
    asyncio.create_task(_watch_wake(device_id))
    return {"sent": True}


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


@app.post("/api/devices/{device_id}/rename")
async def api_device_rename(device_id: str, request: Request):
    body = await request.json()
    name = str(body.get("name", "")).strip()[:80]
    if not name:
        raise HTTPException(400, i18n.t("error.invalid_name"))
    port = body.get("port")
    if port is not None:
        try:
            port = int(port)
            if not (1 <= port <= 65535):
                raise ValueError
        except (ValueError, TypeError):
            raise HTTPException(400, "Porta non valida")
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


def _bg(coro) -> None:
    """Runs a coroutine behind the answer, keeping it alive and logging its failure."""
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)

    def done(t):
        _bg_tasks.discard(t)
        if not t.cancelled() and t.exception():
            logger.error("Aggiornamento in secondo piano non riuscito: %s", t.exception())
    task.add_done_callback(done)


@app.post("/api/devices/{device_id}/override")
async def api_device_override(device_id: str, request: Request):
    """Brand and/or type chosen by hand ("brand", "type"); null = back to automatic."""
    body = await request.json()
    updated = None
    if "ha_share" in body:   # share with Home Assistant (true) or remove from HA (false)
        updated = devices_config.set_override(device_id, "ha_share", "1" if body["ha_share"] is True else None) or updated
        mqtt_service.refresh()
    if "focus" in body:      # "device under examination": its card, history and a note go in the export for analysis
        if body["focus"] is True:
            others = [d for d in devices_config.load_devices() if d.get("focus") and d["id"] != device_id]
            if len(others) >= devices_config.FOCUS_MAX:
                raise HTTPException(409, "Troppi dispositivi segnalati")
            note = str(body.get("focus_note") or "").strip()[:devices_config.FOCUS_NOTE_MAX] or None
            updated = devices_config.set_override(device_id, "focus", "1") or updated
            devices_config.set_override(device_id, "focus_note", note)
        else:
            updated = devices_config.set_override(device_id, "focus", None) or updated
            devices_config.set_override(device_id, "focus_note", None)
    for key, field in (("brand", "brand_user"), ("type", "type_user")):
        if key not in body:
            continue
        value = body[key]
        value = str(value).strip()[:40] if value else None
        if key == "type" and value and value not in ha_data.TYPE_ORDER + ("generic",):
            raise HTTPException(400, "Tipo non valido")
        updated = devices_config.set_override(device_id, field, value) or updated
    if not updated:
        raise HTTPException(404, "Dispositivo non trovato")
    logger.info("Scelta manuale su %s: %s", device_id, {k: body[k] for k in ("brand", "type", "ha_share", "focus") if k in body})
    # The device is read again behind the answer (a probe over the network takes seconds): the page already shows the choice,
    # and the card is sent again to it (event) as soon as the reading is done.
    _bg(state.refresh_device(device_id))
    return {"ok": True}


@app.delete("/api/devices/{device_id}")
async def api_device_delete(device_id: str, ignore: bool = False):
    gone = state.devices.get(device_id) or {}
    if ignore:
        # Before deleting it: what we know about the device is needed to recognize it later.
        known = state.devices.get(device_id) or {}
        name = None if known.get("name") == known.get("ip") else known.get("name")
        mac = known.get("mac") or state._last_mac.get(device_id)
        if known.get("ip"):
            await asyncio.to_thread(blocklist.add_host, known["ip"], mac, name, f"{known.get('name') or known['ip']} · {known['ip']}")
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




@app.post("/api/devices/rescan")
async def api_devices_rescan(request: Request):
    """Re-run a deep scan (services, web page title) on the
    devices chosen by the user. Slow on purpose: it must be launched by hand,
    not on every automatic refresh. Streaming (SSE): one event per completed
    device, to show the real progress in the pop-up."""
    body = await request.json()
    ids = set(body.get("ids", []))
    devices = [d for d in devices_config.load_devices() if d["id"] in ids]
    local_ips = set(await filter_local_ips([d["ip"] for d in devices]))
    devices = [d for d in devices if d["ip"] in local_ips]
    logger.info("Scansione approfondita avviata su %d dispositivi: %s", len(devices), ", ".join(d["ip"] for d in devices))
    state.rescan_started([d["id"] for d in devices])
    try:
        # The deep profile's batch functions (mDNS, SSDP: a single broadcast for
        # the whole LAN) must be run only once, not repeated for every device.
        batch = await pipeline.prepare_batch("deep", [d["ip"] for d in devices])
    except Exception:
        for d in devices:
            state.rescan_finished(d["id"])
        raise

    async def rescan_one(d: dict) -> dict:
        try:
            await rescan_device(d, batch)
        except Exception:
            logger.exception("%s (%s) scansione fallita", d["ip"], d.get("name") or d["ip"])
        finally:
            state.rescan_finished(d["id"])
        return d

    # Tasks created here and not in the generator: if the browser changes page the stream
    # is interrupted but the scans carry on to the end.
    tasks = [asyncio.create_task(rescan_one(d)) for d in devices]
    for task in tasks:
        state.track(task)

    async def stream():
        total = len(devices)
        yield _sse({"type": "total", "total": total})
        done = 0
        for task in asyncio.as_completed(tasks):
            d = await task
            done += 1
            yield _sse({"type": "progress", "done": done, "total": total, "name": d.get("name") or d["ip"], "id": d["id"]})
        logger.info("Scansione approfondita completata (%d dispositivi)", total)
        yield _sse({"type": "complete", "rescanned": total})

    return StreamingResponse(stream(), media_type="text/event-stream", headers=SSE_HEADERS)


@app.get("/api/devices/{device_id}/presence")
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


