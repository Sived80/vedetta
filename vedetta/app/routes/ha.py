# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""Home Assistant-style dashboard (/ha) and its JSON APIs (/api/ha/*).

Designed to live in an iframe of an HA dashboard. It changes nothing in the
classic dashboard: it reads the shared state (state) and the history (history) and
for actions (refresh, wake, rename, ignore) the UI uses the already existing
endpoints of main.py."""
import asyncio
import json
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates


from .. import applog, external, i18n, runtime
from ..analysis import digest, quality, recurrence
from ..networks import registry
from ..export import inventory
from ..ha import analysis_view, ha_data, ha_tz, ha_update, health_view, passive_view
from ..ha.device_debug import device_debug
from ..storage import firststart, health_hidden, journal, passive_store, starhint
from ..scan import latency
from ..recognition import oui_update, roles
from ..storage.history import history
from ..ingress import template_context
from ..state import state
from ..recognition import evidence
from ..ha import ha_registry
from ..assets import static_version
from .bodies import json_dict

BASE_DIR = Path(__file__).resolve().parent.parent
router = APIRouter()
templates = Jinja2Templates(directory=BASE_DIR / "templates", context_processors=[template_context])  # `base` in the templates

# Same headers as the SSE stream in main.py: without them, proxies and browsers may
# buffer the response instead of delivering it one piece at a time.
SSE_HEADERS = {"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}

THEMES = ("auto", "light", "dark")
MAX_HOURS = 24 * 30


templates.env.globals["static_version"] = static_version
templates.env.globals["t"] = i18n.t


def _hours(hours: int) -> int:
    return max(1, min(int(hours), MAX_HOURS))


@router.get("/ha", response_class=HTMLResponse)
async def ha_page(request: Request, theme: str = "auto", bg: str = "", compact: str = "0", limit: int = 6):
    """Page. The address parameters reach the template already validated, and it
    writes them on the <html> element before the first paint (no theme flashes)."""
    lang, chosen = i18n.resolve_request(request)
    theme = theme if theme in THEMES else "auto"
    return templates.TemplateResponse(
        request,
        "ha.html",
        {
            "lang": lang, "lang_auto": not chosen, "languages": i18n.available(), "js_strings": i18n.js_table(lang),
            "theme": theme, "transparent": bg == "transparent", "compact": _flag(compact),
            "limit": max(1, min(limit, 30)), "docker": runtime.is_docker(),
        },
    )


def _flag(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


@router.get("/api/ha/devices")
async def api_ha_devices(request: Request):
    """Compact list for the UI. rev is the state revision: the
    /api/ha/events?rev=<rev> stream sends only what changes after this list.
    ready=false until the first check cycle is finished."""
    i18n.use_request(request)
    seen = passive_view.compact_all(await asyncio.to_thread(passive_store.snapshot))      # the devices Home Assistant sees: cards like the others, apart from what cannot be known without probing them
    return {"rev": state.rev, "ready": state.ready.is_set(), "devices": with_deep(ha_data.compact_all(state.sorted_devices())) + seen,
            "analysis": analysis_view.snapshot()}


@router.get("/api/ha/devices/{device_id}/debug")
async def api_ha_device_debug(device_id: str):
    """Why the device is the way it is: category scores, name candidates, brand and DHCP fingerprint,
    scan state. Only for the page's debug mode (taps on the title)."""
    out = device_debug(device_id)
    if out is None:
        raise HTTPException(404, "Dispositivo non trovato")
    return out


@router.get("/api/ha/devices/{device_id}/evidence")
async def api_ha_device_evidence(device_id: str):
    """Evidence card of the device sheet: what decided name, brand and group, how sure the app is and what it rejected."""
    mac = passive_store.mac_of(device_id)
    if mac:     # a device Home Assistant sees: nothing was worked out, everything is what Home Assistant says (or the user chose)
        item = (await asyncio.to_thread(passive_store.snapshot))["adopted"].get(mac)
        if item is None:
            raise HTTPException(404, "Dispositivo non trovato")
        return passive_view.evidence(item)
    out = device_debug(device_id)
    if out is None:
        raise HTTPException(404, "Dispositivo non trovato")
    return evidence.summarize(out, state.devices.get(device_id) or {})


@router.get("/api/ha/health")
async def api_ha_health(shadow: bool = False):
    """The network-health findings with who, what and when, of the rules that are shown; with ?shadow=1 (the page's debug mode) the ones in shadow too."""
    return {"running": health_view.running(), "findings": await asyncio.to_thread(health_view.page, shadow=shadow), "report": await asyncio.to_thread(health_view.report, shadow=shadow),
            "hidden": await asyncio.to_thread(health_hidden.load)}


@router.post("/api/ha/health/hidden")
async def api_ha_health_hidden(request: Request):
    """Hide or show again findings ({"hide": [ids], "show": [ids]}); the answer is the list now kept, the same for every browser."""
    body = await json_dict(request)
    hide, show = body.get("hide", []), body.get("show", [])
    if not isinstance(hide, list) or not isinstance(show, list):
        raise HTTPException(400, "hide and show must be lists")
    _refuse_too_long(hide, show)
    return {"hidden": await asyncio.to_thread(health_hidden.apply, hide, show)}


def _refuse_too_long(*lists: list) -> None:
    """More ids than the most ever kept is not a choice made on the page: a 400 at once, before a worker thread goes through them."""
    if any(len(ids) > health_hidden.MAX_HIDDEN for ids in lists):
        raise HTTPException(400, i18n.t("error.invalid_body"))


@router.get("/api/ha/registry/status")
async def api_ha_registry_status():
    """State of the Home Assistant registry reading (for debugging)."""
    return ha_registry.status()


@router.get("/api/ha/summary")
async def api_ha_summary(request: Request):
    i18n.use_request(request)
    new_devices = await state.new_devices_event()
    summary = ha_data.build_summary(
        state.sorted_devices(), state.poll_info(), state.activity_info(), new_devices, state.rev,
    )
    from ..ha.mqtt_ha import version
    return {**summary, "roles": roles.page_view(), "mqtt": _mqtt_info(), "version": version(), "star_hint": await _star_hint(),
            "update": ha_update.snapshot(), "external": await asyncio.to_thread(_external_info), "learning_until": await _learning_until()}


def _external_info() -> dict:
    """The three functions that reach the internet and whether each is on (add-on options): the page shows them in a tile, with a button to the
    app's Configuration page in Home Assistant where they are set (its slug; None outside Home Assistant: no button)."""
    return {**external.status(), "mac_database": {"on": oui_update.auto_update_enabled(), "updated": oui_update.meta()["updated"]},
            "app_slug": ha_update.app_slug()}


def _mqtt_info() -> dict:
    from ..ha.mqtt_ha import service
    return service.link()


def _mqtt_event() -> dict:
    """The link with the broker, as the picture of the moment a client gets when it connects (then the changes come as events of the bus)."""
    from ..ha.mqtt_ha import service
    return service.event()


async def _star_hint() -> bool:
    """Whether the one-time invitation to star the project may appear (storage/starhint.py). The age of the installation is read once."""
    global _first_ts
    if starhint.done():
        return False
    if _first_ts is None:
        _first_ts = await asyncio.to_thread(history.first_event_ts)
    return starhint.should_show(_first_ts)


_first_ts: float | None = None


async def _learning_until() -> float | None:
    """Until when the page shows the notice of the first hours (brands and types can still change), or None (storage/firststart.py)."""
    at = firststart.known()          # read once (a file, maybe the history): then from memory
    if at is None:
        at = await asyncio.to_thread(firststart.first_start, history.first_event_ts)
    return firststart.learning_until(at)


@router.post("/api/ha/star")
async def api_ha_star():
    """The invitation has been shown: it will not come back."""
    await asyncio.to_thread(starhint.mark_done)
    return {"ok": True}


@router.get("/api/ha/logbook")
async def api_ha_logbook(request: Request, limit: int = 30, level: str = "min"):
    """Tiered log. min: online/offline changes (with the device's name and type);
    normal: + notices, devices added/deleted, pause; detail: + the work of the
    service (searches, analyses, network roles, DHCP, internet)."""
    i18n.use_request(request)
    limit = max(1, min(int(limit), 200))
    wide = level in ("normal", "detail")
    events = await _presence_events(limit, wide)
    if not wide:
        # Minimum: only fixed devices on the dashboard (a phone coming and going is not news) and only the important notices.
        events = [e for e in events if e.get("known") and not (state.devices.get(e["device_id"]) or {}).get("is_mobile")]
        events += _journal_events(limit, True)
        events = _newest(events, limit)
    else:
        if level == "detail":
            events += _trace_events(limit)
        # In the detailed view the "service" entries of the event log are already in the trace: only the normal ones are kept.
        events = _newest(events + _journal_events(limit, False), limit)
    return {"events": events, "level": level if wide else "min"}


def _journal_events(limit: int, important_only: bool) -> list[dict]:
    return [{"id": "j%s" % j["id"], "kind": "event", "level": j["level"], "ts": j["ts"], "icon": j.get("icon"),
             "message": i18n.t(j["key"], **j.get("params", {}))}
            for j in journal.entries("normal", limit) if not important_only or j["key"] in journal.IMPORTANT]


def _trace_events(limit: int) -> list[dict]:
    """The service trace (the same as the /log page), with the icon of its level. The texts stay as the service writes them."""
    icons = {"WARNING": "alert", "ERROR": "alert-circle", "CRITICAL": "alert-circle"}
    return [{"id": "l%d-%d" % (int(entry["ts"] * 1000), n), "kind": "event", "level": "detail", "ts": entry["ts"],
             "icon": icons.get(entry.get("level"), "history"), "message": entry.get("message", "")}
            for n, entry in enumerate(applog.get_entries()[:limit]) if entry.get("ts") is not None]


def _newest(events: list[dict], limit: int) -> list[dict]:
    return sorted(events, key=lambda e: e["ts"], reverse=True)[:limit]


async def _presence_events(limit: int, wide: bool) -> list[dict]:
    """Online/offline changes. In the minimum view more rows are read because the changes of mobile devices are discarded."""
    rows = await asyncio.to_thread(ha_data.recent_presence, limit if wide else limit * 4)
    events = ha_data.logbook_entries(rows, state.devices, ha_data.config_map())
    for e in events:
        e["kind"] = "presence"
        e["id"] = "p%s" % e["id"]
    return events


@router.get("/api/ha/history")
async def api_ha_history_all(hours: int = 24):
    """Online/offline segments of all devices in a single call
    (for the mini bar of each tile)."""
    hours = _hours(hours)
    adopted = [passive_store.id_of(m) for m in (await asyncio.to_thread(passive_store.snapshot))["adopted"]]
    windows = await asyncio.to_thread(_windows, list(state.devices) + adopted, hours)
    return {"hours": hours, "devices": windows}


def _windows(device_ids: list[str], hours: int) -> dict[str, dict]:
    now = time.time()
    return {i: ha_data.slim_history(history.presence_segments(i, now - hours * 3600, now)) for i in device_ids}


def _is_adopted(device_id: str) -> bool:
    mac = passive_store.mac_of(device_id)
    return bool(mac) and mac in passive_store.snapshot()["adopted"]


@router.get("/api/ha/recurrence/{device_id}")
async def api_ha_recurrence(device_id: str):
    """How the device comes and goes over the last 30 days (analysis/recurrence.py): its class, the active days and the strip."""
    if device_id not in state.devices and not _is_adopted(device_id):
        raise HTTPException(404, "Dispositivo non trovato")
    return await asyncio.to_thread(_recurrence, device_id)


def _recurrence(device_id: str) -> dict:
    now, tz = time.time(), ha_tz.zone()
    segments = history.presence_segments(device_id, recurrence.window_start(now, tz), now)["segments"]
    return recurrence.recurrence(segments, history.first_presence([device_id]).get(device_id), now, tz)


@router.get("/api/ha/quality/{device_id}")
async def api_ha_quality(device_id: str):
    """The quality of the link over 7 days (analysis/quality.py): typical time and spread, the last value against them, the trend,
    the changes in 24 hours and the longest outage."""
    if device_id not in state.devices and not _is_adopted(device_id):
        raise HTTPException(404, "Dispositivo non trovato")
    return await asyncio.to_thread(_quality, device_id)


def _quality(device_id: str) -> dict:
    now = time.time()
    since = now - 7 * 86400
    return quality.quality(history.latency_points(device_id, since, now), history.presence_segments(device_id, since, now)["segments"], now)


@router.get("/api/ha/identity/{device_id}")
async def api_ha_identity(device_id: str):
    """What Vedetta called the card over the last 90 days: the changes of name and brand, newest first, with their source."""
    if device_id not in state.devices and not _is_adopted(device_id):
        raise HTTPException(404, "Dispositivo non trovato")
    return {"changes": await asyncio.to_thread(history.identity_changes, device_id)}


@router.get("/api/ha/digest")
async def api_ha_digest(hours: int = 12):
    """The summary of the last hours (analysis/digest.py): new, back after a long absence, gone silent; only the changes of the window."""
    hours = _hours(hours)
    return await asyncio.to_thread(_digest, hours, dict(state.devices))      # a copy taken on the loop: the cycle adds and removes cards meanwhile


def _digest(hours: int, devices: dict) -> dict:
    now = time.time()
    start = now - hours * 3600
    ids = list(devices)
    first = history.first_presence(ids)
    cards = {i: {"first_seen": first.get(i), "online": bool(d.get("online")), "last_seen": now if d.get("online") else d.get("last_seen"),
                 "is_mobile": bool(d.get("is_mobile")), "watched": registry.may_add(d.get("ip"))} for i, d in devices.items()}
    out = digest.digest(cards, history.returns_after(start, now, digest.DEFAULT_BACK_S), start, now, installed_at=history.first_event_ts())
    out["labels"] = {i: (devices[i].get("name") or devices[i].get("ip") or i) if i in devices else i
                     for i in {*out["new"], *out["silent"], *(b["id"] for b in out["back"])}}
    return out


@router.get("/api/ha/inventory")
async def api_ha_inventory(request: Request, format: str = "csv", hide: int = 0):  # noqa: A002  the name of the query parameter
    """The person's inventory (export/inventory.py): CSV or JSON, with «hide MAC and IP» (hide=1)."""
    if format not in ("csv", "json"):
        raise HTTPException(400, "Valore non valido: format")
    i18n.use_request(request)
    body = await asyncio.to_thread(_inventory, format, bool(hide), state.sorted_devices())     # the cards read on the loop
    media = "text/csv; charset=utf-8" if format == "csv" else "application/json; charset=utf-8"
    name = time.strftime("vedetta-inventory-%Y%m%d.") + format
    return Response(body, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


def _inventory(fmt: str, hide: bool, devices: list[dict]) -> str:
    cards = [{**c, "area": ((d.get("ha_registry") or {}).get("area"))} for c, d in zip(ha_data.compact_all(devices), devices)]
    table = inventory.rows(cards, history.first_presence([c["id"] for c in cards]), time.time())
    table = inventory.hidden(table) if hide else table
    return inventory.to_csv(table) if fmt == "csv" else inventory.to_json(table)


@router.get("/api/ha/history/{device_id}")
async def api_ha_history(device_id: str, request: Request, hours: int = 24):
    """Segments of one device (same format as history.presence_segments)."""
    i18n.use_request(request)
    if device_id not in state.devices and not _is_adopted(device_id):
        raise HTTPException(404, i18n.t("ha.error.not_found"))
    hours = _hours(hours)
    now = time.time()
    window = await asyncio.to_thread(history.presence_segments, device_id, now - hours * 3600, now)
    points = await asyncio.to_thread(history.latency_points, device_id, now - hours * 3600, now)
    # Response time reduced to ~120 points (average per bucket) for a light chart.
    series = latency.reduce_series(points, now - hours * 3600, now)
    return {"device_id": device_id, "hours": hours, **window, "latency": series}


def with_deep(cards: list[dict]) -> list[dict]:
    """The cards with "deep_ok": whether the deep search may ask the device (registry.allowed would keep its address). A device of a network
    behind the router set to "presence only" never is: the badge of the page must not count it, or its number never goes down. Unmarked
    while the main network is not known yet."""
    ok = registry.deep_allowed_now([c.get("ip") for c in cards if c.get("ip")])
    return cards if ok is None else [{**c, "deep_ok": c.get("ip") in ok} for c in cards]


def localize(event: dict, cfg: dict[str, dict]) -> dict:
    """Shared-state event -> JSON for this UI: devices in
    compact format, notices as translated text (no HTML)."""
    if event["type"] == "device" and "device" in event:
        device = event["device"]
        return {**{k: v for k, v in event.items() if k != "device"},
                "device": with_deep([ha_data.compact_device(device, cfg.get(device["id"]))])[0]}
    if event["type"] == "alert" and "key" in event:
        rest = {k: v for k, v in event.items() if k != "params"}
        return {**rest, "message": i18n.t(event["key"], **event.get("params", {}))}
    return event


@router.get("/api/ha/events")
async def api_ha_events(request: Request, rev: int = 0):
    """SSE stream like /api/events but with JSON instead of HTML: events
    device (compact format), removed, poll, activity, alert, new_devices."""
    queue = state.subscribe()
    lang = i18n.use_request(request)

    def frame(event: dict) -> str:
        event = localize(event, ha_data.config_map())
        return "event: " + event["type"] + "\ndata: " + json.dumps(event) + "\n\n"

    async def stream():
        i18n.use(lang)  # the generator runs in a separate task: the language is set again here
        try:
            async for text in _opening(rev, frame):
                yield text
            async for text in _live(queue, request, frame):
                yield text
        finally:
            state.unsubscribe(queue)

    return StreamingResponse(stream(), media_type="text/event-stream", headers=SSE_HEADERS)


PING_SECONDS = 15      # a quiet stream sends a ping this often, so a proxy does not close it and a gone client is noticed
# A named event and not a comment: the page sees it (a comment never reaches EventSource) and knows the stream is alive (#55).
PING_FRAME = "event: ping\ndata: {}\n\n"


async def _opening(rev: int, frame):
    """What a client gets when it connects: the retry hint, the events it missed, then the picture of the moment."""
    yield "retry: 3000\n\n"
    for event in state.catch_up(rev):
        yield frame(event)
    yield frame(state.poll_info())
    yield frame(state.activity_info())
    yield frame(await state.new_devices_event())
    yield frame(roles.event())
    yield frame(analysis_view.event())
    yield frame(_mqtt_event())


async def _live(queue, request, frame):
    """Every event of the bus as a frame; a ping when nothing comes; ends when the state dropped the queue or the client went away."""
    while True:
        try:
            event = await asyncio.wait_for(queue.get(), timeout=PING_SECONDS)
        except asyncio.TimeoutError:
            if not state.is_subscribed(queue) or await request.is_disconnected():
                return
            yield PING_FRAME
            continue
        yield frame(event)
