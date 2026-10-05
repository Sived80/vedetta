"""Dashboard in stile Home Assistant (/ha) e relative API JSON (/api/ha/*).

Pensata per stare in un iframe di una plancia di HA. Non modifica nulla della
dashboard classica: legge lo stato condiviso (state) e lo storico (history) e
per le azioni (aggiorna, wake, rinomina, ignora) la UI usa gli endpoint gia'
esistenti di main.py."""
import asyncio
import json
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from . import applog, ha_data, i18n, journal, latency, roles
from .history import history
from .ingress import template_context
from .state import state

BASE_DIR = Path(__file__).resolve().parent
router = APIRouter()
templates = Jinja2Templates(directory=BASE_DIR / "templates", context_processors=[template_context])  # `base` nei template

# Stessi header del flusso SSE di main.py: senza, proxy e browser possono
# bufferizzare la risposta invece di consegnarla un pezzo alla volta.
SSE_HEADERS = {"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}

THEMES = ("auto", "light", "dark")
MAX_HOURS = 24 * 30


def static_version(rel_path: str) -> str:
    """Come in main.py: data di modifica del file, da mettere in ?v= cosi' dopo
    un deploy il browser scarica sempre la versione nuova."""
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
    """Pagina. I parametri dell'indirizzo arrivano gia' validati al template, che
    li scrive sull'elemento <html> prima del primo disegno (niente lampi di tema)."""
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
    """Elenco compatto per la UI. rev e' la revisione dello stato: il flusso
    /api/ha/events?rev=<rev> manda solo cio' che cambia dopo questo elenco.
    ready=false finche' il primo ciclo di controllo non e' finito."""
    i18n.use_request(request)
    return {"rev": state.rev, "ready": state.ready.is_set(), "devices": ha_data.compact_all(state.sorted_devices())}


@router.get("/api/ha/devices/{device_id}/debug")
async def api_ha_device_debug(device_id: str):
    """Perche' il dispositivo e' cosi': punteggi di categoria, candidati del nome, marca e impronta DHCP,
    stato della scansione. Solo per la modalita' debug della pagina (tocchi sul titolo)."""
    out = device_debug(device_id)
    if out is None:
        raise HTTPException(404, "Dispositivo non trovato")
    return out


def device_debug(device_id: str) -> dict | None:
    from . import dhcp, ha_registry, identity, mdns_listener, naming
    device = state.devices.get(device_id)
    if device is None:
        return None
    cfg = ha_data.config_map().get(device_id) or {}
    kinds: dict[str, int] = {}
    evidence = ha_data.type_evidence(device, cfg.get("adapter"), kinds)
    scores = ha_data._aggregate(evidence)
    # per ogni (categoria, famiglia) conta solo l'indizio piu' alto: gli altri sono "ripetizioni" dello stesso fatto
    top: dict = {}
    for e in evidence:
        top[(e["group"], e["family"])] = max(top.get((e["group"], e["family"]), 0), e["pts"])
    shown = [{**e, "counted": e["pts"] == top[(e["group"], e["family"])]} for e in evidence]
    shown.sort(key=lambda e: (e["group"], -e["pts"]))
    scan = cfg.get("scan_info") or {}
    extra = device.get("extra") or {}
    mac = (device.get("mac") or "").lower()
    entry = dhcp.seen.get(mac) or {}

    def cand(source: str, raw):
        return {"source": source, "raw": raw, "cleaned": naming.clean_name(raw) if raw else None} if raw else None
    candidates = [c for c in (
        cand("adapter", scan.get("api_name")), cand("mdns", scan.get("mdns_name")), cand("upnp", scan.get("upnp_name")),
        cand("dhcp", entry.get("hostname")), cand("netbios", scan.get("netbios_name")), cand("onvif", scan.get("onvif_name")),
        cand("tls", naming.cn_host(scan.get("tls_subject")) if scan.get("tls_subject") else None),
        cand("web", scan.get("http_title"))) if c]
    return {
        "type": {"chosen": ha_data.effective_type(device, cfg), "manual": cfg.get("type_user"),
                 "scores": dict(sorted(scores.items(), key=lambda kv: -kv[1])),
                 "kinds": dict(sorted(kinds.items(), key=lambda kv: -kv[1])),
                 "evidence": shown, "margin_below": ha_data.MARGIN_BELOW,
                 "min_score": ha_data.MIN_TYPE_SCORE},
        "name": {"shown": device.get("name"), "source": cfg.get("name_source"), "candidates": candidates,
                 "placeholder": naming.is_placeholder(device.get("name"))},
        "brand": {"brand": device.get("brand"), "manual": cfg.get("brand_user"), "source": device.get("brand_source"),
                  "evidence": device.get("brand_evidence"), "confidence": device.get("brand_confidence"),
                  "declared": device.get("brand_declared"), "vendor": device.get("vendor"), "vendor_role": device.get("vendor_role")},
        "mobile": {"is_mobile": device.get("is_mobile"), "mode": cfg.get("mobile"), "private_mac": identity.is_private_mac(device.get("mac")),
                   "dhcp_os_family": dhcp.os_family(device.get("mac")), "churn_7d": identity.presence_churn(device_id),
                   "battery": device.get("battery"), "battery_source": device.get("battery_source")},
        "dhcp": {k: v for k, v in entry.items() if k != "seen"},
        "roles": {"roles": roles.roles_for(device.get("ip")), "upnp_types": roles.upnp_types(device.get("ip"))},
        "scan": {k: scan.get(k) for k in ("scanned_at", "slow_scan", "full_ports_at", "services_at", "mdns_model", "mdns_manufacturer",
                                          "mdns_services", "http_server", "http_title", "tls_subject", "ssh_hostkey") if scan.get(k)},
        "extra_keys": sorted(extra),
        "wol": {"ok": bool(cfg.get("wol_ok"))},
        "ha_registry": ha_registry.lookup(device.get("mac"), device.get("ip")),
        "mdns_memory": mdns_listener.lookup(device.get("mac"), device.get("ip")),
    }


@router.post("/api/export")
async def api_export():
    """Zip per l'analisi (dati, stato e perche' di ogni dispositivo). POST: non si scarica per sbaglio con un link."""
    from fastapi.responses import Response
    from . import export
    data = await asyncio.to_thread(export.build_zip)
    name = "vedetta-analisi-" + time.strftime("%Y%m%d-%H%M%S") + ".zip"
    return Response(content=data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@router.get("/api/ha/registry/status")
async def api_ha_registry_status():
    """Stato della lettura del registro di Home Assistant (per il debug)."""
    from . import ha_registry
    return ha_registry.status()


def _mqtt_info() -> dict:
    from .mqtt_ha import service
    st = service.status()
    return {"active": st["active"], "connected": st["connected"]}


@router.get("/api/ha/summary")
async def api_ha_summary(request: Request):
    i18n.use_request(request)
    new_devices = await state.new_devices_event()
    summary = ha_data.build_summary(
        state.sorted_devices(), state.poll_info(), state.activity_info(), new_devices, state.rev,
    )
    return {**summary, "roles": roles.snapshot(), "mqtt": _mqtt_info()}


@router.get("/api/ha/logbook")
async def api_ha_logbook(request: Request, limit: int = 30, level: str = "min"):
    """Registro a livelli. min: cambi online/offline (con nome e tipo del dispositivo);
    normal: + avvisi, dispositivi aggiunti/eliminati, pausa; detail: + il lavoro del
    servizio (ricerche, analisi, ruoli di rete, DHCP, internet)."""
    i18n.use_request(request)
    limit = max(1, min(int(limit), 200))
    # Minimo: si leggono piu' righe perche' i cambi di stato dei dispositivi mobili si scartano.
    rows = await asyncio.to_thread(ha_data.recent_presence, limit * 4 if level not in ("normal", "detail") else limit)
    events = ha_data.logbook_entries(rows, state.devices, ha_data.config_map())
    for e in events:
        e["kind"] = "presence"
        e["id"] = "p%s" % e["id"]
    if level not in ("normal", "detail"):
        # Minimo: solo i dispositivi fissi in plancia (un telefono che entra ed esce non e' una notizia)
        # e solo gli avvisi importanti.
        # Solo dispositivi ancora in plancia e non mobili.
        events = [e for e in events if e.get("known") and not (state.devices.get(e["device_id"]) or {}).get("is_mobile")]
        for j in journal.entries("normal", limit):
            if j["key"] in journal.IMPORTANT:
                events.append({"id": "j%s" % j["id"], "kind": "event", "level": j["level"], "ts": j["ts"], "icon": j.get("icon"),
                               "message": i18n.t(j["key"], **j.get("params", {}))})
        events.sort(key=lambda e: e["ts"], reverse=True)
        events = events[:limit]
    if level == "detail":
        # Dettagliato: anche la traccia del servizio (la stessa della pagina /log), con
        # l'icona del suo livello. I testi restano come li scrive il servizio.
        icons = {"WARNING": "alert", "ERROR": "alert-circle", "CRITICAL": "alert-circle"}
        for n, entry in enumerate(applog.get_entries()[:limit]):
            if entry.get("ts") is None:
                continue
            events.append({"id": "l%d-%d" % (int(entry["ts"] * 1000), n), "kind": "event", "level": "detail", "ts": entry["ts"],
                           "icon": icons.get(entry.get("level"), "history"), "message": entry.get("message", "")})
    if level in ("normal", "detail"):
        # Nel dettagliato le voci "di servizio" del registro eventi sono gia' nella traccia
        # qui sopra (stesso fatto, scritto dal servizio): si tengono solo quelle normali.
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
    """Segmenti online/offline di tutti i dispositivi in una sola chiamata
    (per la mini barra di ogni tile)."""
    hours = _hours(hours)
    windows = await asyncio.to_thread(_windows, list(state.devices), hours)
    return {"hours": hours, "devices": windows}


@router.get("/api/ha/history/{device_id}")
async def api_ha_history(device_id: str, request: Request, hours: int = 24):
    """Segmenti di un dispositivo (stesso formato di history.presence_segments)."""
    i18n.use_request(request)
    if device_id not in state.devices:
        raise HTTPException(404, i18n.t("ha.error.not_found"))
    hours = _hours(hours)
    now = time.time()
    window = await asyncio.to_thread(history.presence_segments, device_id, now - hours * 3600, now)
    points = await asyncio.to_thread(history.latency_points, device_id, now - hours * 3600, now)
    # Tempo di risposta ridotto a ~120 punti (media per fascia) per un grafico leggero.
    series = latency.reduce_series(points, now - hours * 3600, now)
    return {"device_id": device_id, "hours": hours, **window, "latency": series}


def localize(event: dict, cfg: dict[str, dict]) -> dict:
    """Evento dello stato condiviso -> JSON per questa UI: i dispositivi in
    formato compatto, gli avvisi come testo tradotto (niente HTML)."""
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
    """Flusso SSE come /api/events ma con JSON al posto dell'HTML: eventi
    device (formato compatto), removed, poll, activity, alert, new_devices."""
    queue = state.subscribe()
    lang = i18n.use_request(request)

    def frame(event: dict) -> str:
        event = localize(event, ha_data.config_map())
        return "event: " + event["type"] + "\ndata: " + json.dumps(event) + "\n\n"

    async def stream():
        i18n.use(lang)  # il generatore gira in un task a parte: la lingua si reimposta qui
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
