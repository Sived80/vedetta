"""Home Assistant-style dashboard (/ha) and its JSON APIs (/api/ha/*).

Designed to live in an iframe of an HA dashboard. It changes nothing in the
classic dashboard: it reads the shared state (state) and the history (history) and
for actions (refresh, wake, rename, ignore) the UI uses the already existing
endpoints of main.py."""
import asyncio
import secrets
import json
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates


from ..applog import logger
from .. import applog, assets, i18n
from ..ha import ha_data
from ..ha.device_debug import device_debug
from ..storage import journal, starhint
from ..scan import latency
from ..recognition import roles
from ..storage.history import history
from ..ingress import template_context
from ..state import state

BASE_DIR = Path(__file__).resolve().parent.parent
router = APIRouter()
templates = Jinja2Templates(directory=BASE_DIR / "templates", context_processors=[template_context])  # `base` in the templates

# Same headers as the SSE stream in main.py: without them, proxies and browsers may
# buffer the response instead of delivering it one piece at a time.
SSE_HEADERS = {"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}

THEMES = ("auto", "light", "dark")
MAX_HOURS = 24 * 30


def static_version(rel_path: str) -> str:
    """As in main.py: file modification date, to put in ?v= so that after
    a deploy the browser always downloads the new version."""
    if rel_path in assets.BUNDLES:
        return assets.version(rel_path)
    try:
        return str(int((BASE_DIR / "static" / rel_path).stat().st_mtime))
    except OSError:
        return "0"


templates.env.globals["static_version"] = static_version
templates.env.globals["t"] = i18n.t


def _flag(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


def _hours(hours: int) -> int:
    return max(1, min(int(hours), MAX_HOURS))


@router.get("/ha", response_class=HTMLResponse)
async def ha_page(request: Request, theme: str = "auto", bg: str = "", compact: str = "0", limit: int = 6):
    """Page. The address parameters reach the template already validated, and it
    writes them on the <html> element before the first paint (no theme flashes)."""
    lang = i18n.use_request(request)
    theme = theme if theme in THEMES else "auto"
    return templates.TemplateResponse(
        "ha.html",
        {
            "request": request, "lang": lang, "languages": i18n.available(), "js_strings": i18n.js_table(lang),
            "theme": theme, "transparent": bg == "transparent", "compact": _flag(compact),
            "limit": max(1, min(limit, 30)),
        },
    )


@router.get("/api/ha/devices")
async def api_ha_devices(request: Request):
    """Compact list for the UI. rev is the state revision: the
    /api/ha/events?rev=<rev> stream sends only what changes after this list.
    ready=false until the first check cycle is finished."""
    i18n.use_request(request)
    return {"rev": state.rev, "ready": state.ready.is_set(), "devices": ha_data.compact_all(state.sorted_devices())}


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
    from ..recognition import evidence
    out = device_debug(device_id)
    if out is None:
        raise HTTPException(404, "Dispositivo non trovato")
    return evidence.summarize(out, state.devices.get(device_id) or {})


@router.post("/api/export")
async def api_export(plain: bool = False):
    """Zip for analysis (data, state and reasons of every device), anonymised. By default it is encrypted with the
    maintainer's public key (safe to attach to a public issue); ?plain=1 gives the plain zip. POST: so it is not
    downloaded by accident through a link."""
    from fastapi.responses import JSONResponse, Response
    from ..export import export_zip as export, report_crypto
    headers = {"Cache-Control": "no-store"}
    try:
        data = await asyncio.to_thread(export.build_zip)
        headers["X-Vedetta-Omitted"] = str(len(export.last_omitted))      # files left out because they could not be masked safely
    except export.MaskingFailed as exc:
        logger.warning("Export refused: the masking left something readable (%s)", exc)    # kinds and file only, never values
        return JSONResponse({"error": "masking_failed"}, status_code=422, headers=headers)
    except Exception:                                  # whatever else goes wrong: the reason is in the log, the person gets a clear answer
        logger.exception("Export failed")
        return JSONResponse({"error": "export_failed"}, status_code=500, headers=headers)
    if plain:
        name = "vedetta-analisi-" + time.strftime("%Y%m%d-%H%M%S") + ".zip"
        return Response(content=data, media_type="application/zip", headers={**headers, "Content-Disposition": f'attachment; filename="{name}"'})
    try:
        sealed = await asyncio.to_thread(report_crypto.seal, data)
    except report_crypto.CryptoUnavailable:
        return JSONResponse({"error": "encryption_unavailable"}, status_code=501, headers=headers)   # never a plain file by mistake
    name = "vedetta-report-" + secrets.token_hex(3) + ".txt"      # neutral name: no date, no device
    return Response(content=sealed, media_type="text/plain", headers={**headers, "Content-Disposition": f'attachment; filename="{name}"'})


# ---- the export window: an estimate, a job followed step by step, the file once
@router.get("/api/export/info")
async def api_export_info():
    """Bytes of raw data for each of the last days, what the file always has, and the limit: the window draws the columns and
    says how big a period will be with these."""
    from ..export import export_engine
    return await asyncio.to_thread(export_engine.estimate)


def _job_or_404(job_id: str):
    from ..export import export_jobs
    job = export_jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "export not found")
    return job


@router.post("/api/export/jobs")
async def api_export_job_start(request: Request):
    """Body: {"dest": "dev"|"me", "from_day": N, "to_day": M} (days ago: the oldest and the newest included, 0 = today) or
    {"dest": ..., "all": true} for the whole history."""
    from ..export import export_engine, export_jobs
    body = await request.json()
    dest = body.get("dest")
    if dest not in ("dev", "me"):
        raise HTTPException(422, "dest must be dev or me")
    if body.get("all") is True:
        first = last = None
    else:
        try:
            first, last = int(body["from_day"]), int(body.get("to_day", 0))
        except (KeyError, TypeError, ValueError):
            raise HTTPException(422, "from_day and to_day must be numbers") from None
        if not (0 <= last <= first < export_engine.HORIZON_DAYS):
            raise HTTPException(422, "period out of range")
    try:
        job = export_jobs.start(dest, first, last)
    except export_jobs.Busy:
        raise HTTPException(409, "an export is already running") from None
    return export_jobs.snapshot(job)


@router.get("/api/export/jobs/{job_id}")
async def api_export_job(job_id: str):
    from ..export import export_jobs
    return export_jobs.snapshot(_job_or_404(job_id))


@router.post("/api/export/jobs/{job_id}/choices")
async def api_export_job_choices(job_id: str, request: Request):
    """Body: {"choices": {"0": "rm", "1": "keep"}}: what to do with each value the check could not fix."""
    from ..export import export_jobs
    job = _job_or_404(job_id)
    body = await request.json()
    try:
        export_jobs.decide(job, body.get("choices") or {})
    except export_jobs.Busy:
        raise HTTPException(409, "nothing to decide") from None
    return export_jobs.snapshot(job)


@router.post("/api/export/jobs/{job_id}/file")
async def api_export_job_file(job_id: str):
    """The finished file, once. POST so it is not downloaded by accident through a link."""
    from fastapi.responses import Response
    from ..export import export_jobs
    got = export_jobs.take(_job_or_404(job_id))
    if got is None:
        raise HTTPException(409, "the file is not ready")
    data, name, mime = got
    return Response(content=data, media_type=mime, headers={"Cache-Control": "no-store", "Content-Disposition": f'attachment; filename="{name}"'})


@router.delete("/api/export/jobs/{job_id}")
async def api_export_job_cancel(job_id: str):
    from ..export import export_jobs
    export_jobs.forget(job_id)
    return {"ok": True}


@router.get("/api/ha/registry/status")
async def api_ha_registry_status():
    """State of the Home Assistant registry reading (for debugging)."""
    from ..ha import ha_registry
    return ha_registry.status()


def _mqtt_info() -> dict:
    from ..ha.mqtt_ha import service
    st = service.status()
    return {"active": st["active"], "connected": st["connected"]}


@router.get("/api/ha/summary")
async def api_ha_summary(request: Request):
    i18n.use_request(request)
    new_devices = await state.new_devices_event()
    summary = ha_data.build_summary(
        state.sorted_devices(), state.poll_info(), state.activity_info(), new_devices, state.rev,
    )
    from ..ha.mqtt_ha import version
    return {**summary, "roles": roles.snapshot(), "mqtt": _mqtt_info(), "version": version(), "star_hint": await _star_hint()}


async def _star_hint() -> bool:
    """Whether the one-time invitation to star the project may appear (storage/starhint.py). The age of the installation is read once."""
    global _first_ts
    if not starhint.enabled() or starhint.done():
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
    # Minimum: more rows are read because state changes of mobile devices are discarded.
    rows = await asyncio.to_thread(ha_data.recent_presence, limit * 4 if level not in ("normal", "detail") else limit)
    events = ha_data.logbook_entries(rows, state.devices, ha_data.config_map())
    for e in events:
        e["kind"] = "presence"
        e["id"] = "p%s" % e["id"]
    if level not in ("normal", "detail"):
        # Minimum: only fixed devices on the dashboard (a phone coming and going is not news)
        # and only the important notices.
        # Only devices still on the dashboard and not mobile.
        events = [e for e in events if e.get("known") and not (state.devices.get(e["device_id"]) or {}).get("is_mobile")]
        for j in journal.entries("normal", limit):
            if j["key"] in journal.IMPORTANT:
                events.append({"id": "j%s" % j["id"], "kind": "event", "level": j["level"], "ts": j["ts"], "icon": j.get("icon"),
                               "message": i18n.t(j["key"], **j.get("params", {}))})
        events.sort(key=lambda e: e["ts"], reverse=True)
        events = events[:limit]
    if level == "detail":
        # Detailed: also the service trace (the same as the /log page), with
        # the icon of its level. The texts stay as the service writes them.
        icons = {"WARNING": "alert", "ERROR": "alert-circle", "CRITICAL": "alert-circle"}
        for n, entry in enumerate(applog.get_entries()[:limit]):
            if entry.get("ts") is None:
                continue
            events.append({"id": "l%d-%d" % (int(entry["ts"] * 1000), n), "kind": "event", "level": "detail", "ts": entry["ts"],
                           "icon": icons.get(entry.get("level"), "history"), "message": entry.get("message", "")})
    if level in ("normal", "detail"):
        # In the detailed view the "service" entries of the event log are already in the trace
        # above (same fact, written by the service): only the normal ones are kept.
        for j in journal.entries("normal", limit):
            events.append({"id": "j%s" % j["id"], "kind": "event", "level": j["level"], "ts": j["ts"], "icon": j.get("icon"),
                           "message": i18n.t(j["key"], **j.get("params", {}))})
        events.sort(key=lambda e: e["ts"], reverse=True)
        events = events[:limit]
    return {"events": events, "level": level if level in ("normal", "detail") else "min"}


def _windows(device_ids: list[str], hours: int) -> dict[str, dict]:
    now = time.time()
    return {i: ha_data.slim_history(history.presence_segments(i, now - hours * 3600, now)) for i in device_ids}


@router.get("/api/ha/history")
async def api_ha_history_all(hours: int = 24):
    """Online/offline segments of all devices in a single call
    (for the mini bar of each tile)."""
    hours = _hours(hours)
    windows = await asyncio.to_thread(_windows, list(state.devices), hours)
    return {"hours": hours, "devices": windows}


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
            yield "retry: 3000\n\n"
            for event in state.catch_up(rev):
                yield frame(event)
            yield frame(state.poll_info())
            yield frame(state.activity_info())
            yield frame(await state.new_devices_event())
            yield frame(roles.event())
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    if not state.is_subscribed(queue) or await request.is_disconnected():
                        break
                    yield ": ping\n\n"
                    continue
                yield frame(event)
        finally:
            state.unsubscribe(queue)

    return StreamingResponse(stream(), media_type="text/event-stream", headers=SSE_HEADERS)
