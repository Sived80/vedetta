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
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates


from .. import applog, external, i18n
from ..ha import analysis_view, ha_data, ha_update, health_view
from ..ha.device_debug import device_debug
from ..storage import journal, starhint
from ..scan import latency
from ..recognition import oui_update, roles
from ..storage.history import history
from ..ingress import template_context
from ..state import state
from ..recognition import evidence
from ..ha import ha_registry
from ..assets import static_version

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
        "ha.html",
        {
            "request": request, "lang": lang, "lang_auto": not chosen, "languages": i18n.available(), "js_strings": i18n.js_table(lang),
            "theme": theme, "transparent": bg == "transparent", "compact": _flag(compact),
            "limit": max(1, min(limit, 30)),
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
    return {"rev": state.rev, "ready": state.ready.is_set(), "devices": ha_data.compact_all(state.sorted_devices()), "analysis": analysis_view.snapshot()}


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
    out = device_debug(device_id)
    if out is None:
        raise HTTPException(404, "Dispositivo non trovato")
    return evidence.summarize(out, state.devices.get(device_id) or {})


@router.get("/api/ha/health")
async def api_ha_health():
    """The network-health findings with who, what and when, shadow included. Only the page's debug mode asks for it; the judge runs in shadow in any case."""
    return {"running": health_view.running(), "findings": await asyncio.to_thread(health_view.page)}


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
    return {**summary, "roles": roles.snapshot(), "mqtt": _mqtt_info(), "version": version(), "star_hint": await _star_hint(),
            "update": ha_update.snapshot(), "external": await asyncio.to_thread(_external_info)}


def _external_info() -> dict:
    """The three functions that reach the internet and whether each is on (add-on options): the page shows them in a tile."""
    return {**external.status(), "mac_database": {"on": oui_update.auto_update_enabled(), "updated": oui_update.meta()["updated"]}}


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
    windows = await asyncio.to_thread(_windows, list(state.devices), hours)
    return {"hours": hours, "devices": windows}


def _windows(device_ids: list[str], hours: int) -> dict[str, dict]:
    now = time.time()
    return {i: ha_data.slim_history(history.presence_segments(i, now - hours * 3600, now)) for i in device_ids}


@router.get("/api/ha/history/{device_id}")
async def api_ha_history(device_id: str, request: Request, hours: int = 24):
    """Segments of one device (same format as history.presence_segments)."""
    i18n.use_request(request)
    if device_id not in state.devices:
        raise HTTPException(404, i18n.t("ha.error.not_found"))
    hours = _hours(hours)
    now = time.time()
    window = await asyncio.to_thread(history.presence_segments, device_id, now - hours * 3600, now)
    points = await asyncio.to_thread(history.latency_points, device_id, now - hours * 3600, now)
    # Response time reduced to ~120 points (average per bucket) for a light chart.
    series = latency.reduce_series(points, now - hours * 3600, now)
    return {"device_id": device_id, "hours": hours, **window, "latency": series}


def localize(event: dict, cfg: dict[str, dict]) -> dict:
    """Shared-state event -> JSON for this UI: devices in
    compact format, notices as translated text (no HTML)."""
    if event["type"] == "device" and "device" in event:
        device = event["device"]
        return {**{k: v for k, v in event.items() if k != "device"},
                "device": ha_data.compact_device(device, cfg.get(device["id"]))}
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


PING_SECONDS = 15      # a quiet stream sends a comment this often, so a proxy does not close it and a gone client is noticed


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
            yield ": ping\n\n"
            continue
        yield frame(event)
