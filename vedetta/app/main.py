"""Entry point of the service: creates the FastAPI app, starts and stops the background work in the lifespan, and mounts the routes that live in routes/.
A route is the outermost layer: nothing imports this module except the tests (that is why the names of the routes are also reachable here)."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from .storage import devices_config, journal
from .storage.history import history
from .ha import analysis_view, ha_registry, ha_tz, ha_update
from .scan import mdns_listener, dhcp, internet, scanner
from . import i18n, lifecycle, paths
from .state_support import _process_info
from .recognition import roles
from .applog import logger
from .ingress import IngressMiddleware, template_context
from .maintenance import nightly_loop
from .assets import static_version
from .frontend_serving import mount_frontend
from .routes import flows as routes_flows
from .routes.bodies import json_dict
from .routes import brands as routes_brands, export_routes as routes_export, ignored as routes_ignored, ha as routes_ha, mqtt as routes_mqtt
from .ha.mqtt_ha import service as mqtt_service
from .state import state
from .sse import SSE_HEADERS, _sse  # noqa: F401
from .routes.scan_routes import SCAN_INFO_KEYS, _quick_scan, _run_quick_scan, api_scan_cancel, api_scan_deep, api_scan_quick  # noqa: F401
from .routes import scan_routes as routes_scan_routes
from .routes.device_routes import _bg, _bg_tasks, _watch_wake, api_device_delete, api_device_override, api_device_presence, api_device_rename, api_device_wake, api_devices_add, api_devices_rescan  # noqa: F401
from .routes import device_routes as routes_device_routes
from .routes.settings_routes import api_new_devices, api_new_devices_ignore, api_new_devices_ignored, api_new_devices_unignore, api_set_lang, api_settings_get, api_settings_set  # noqa: F401
from .routes import settings_routes as routes_settings_routes

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_: FastAPI):
    await asyncio.to_thread(devices_config.ensure_seq_safely)   # the cards of an older file get their number, once (a copy of the old file is kept)
    heartbeat = lifecycle.start(paths.data_path("run.json"), lambda: _process_info().get("rss_mb"), logger.info)   # how the previous run ended, and the record of this one
    await state.load_history()
    state.start()
    asyncio.create_task(ha_tz.refresh(force=True))   # the user's time zone, from Home Assistant
    nightly = asyncio.create_task(nightly_loop())
    dhcp_transport = await dhcp.start()
    ha_registry.start()  # Home Assistant registry (read-only; empty outside HA)
    ha_update.start()  # is there a newer version of this add-on? (asks the Supervisor for its own card; nothing outside HA)
    mdns_listener.start(state, lent_counts=history.mac_ip_counts)  # Bonjour names: memory and continuous listening
    await mqtt_service.start(state)  # MQTT publishing towards HA (off if not configured)
    roles.start(state, on_change=state.emit_event, on_alert=state.emit_alert,
                dhcp_discover=scanner.dhcp_discover, internet_check=internet.check)  # who does what: gateway, DHCP, DNS, repeaters
    analysis_view.start(on_change=state.emit_event)   # the state of each card: identified, settling or under analysis (read-only)
    logger.info("Servizio avviato")
    yield
    if dhcp_transport:
        dhcp_transport.close()
    nightly.cancel()
    await ha_registry.stop()
    await ha_update.stop()
    await mdns_listener.stop()
    await analysis_view.stop()
    await roles.stop()
    await mqtt_service.stop()
    await state.stop()
    await lifecycle.stop(heartbeat, paths.data_path("run.json"))


app = FastAPI(title="Vedetta", lifespan=lifespan)
app.include_router(routes_brands.router)
app.include_router(routes_ignored.router)
app.include_router(routes_flows.router)
app.include_router(routes_ha.router)
app.include_router(routes_export.router)
app.include_router(routes_mqtt.router)
app.include_router(routes_scan_routes.router)
app.include_router(routes_device_routes.router)
app.include_router(routes_settings_routes.router)


mount_frontend(app, BASE_DIR / "static")
app.add_middleware(IngressMiddleware)  # ingress prefix -> request.state.base; optional 403 outside the Supervisor
templates = Jinja2Templates(directory=BASE_DIR / "templates", context_processors=[template_context])  # `base` in the templates


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


@app.post("/api/refresh")
async def api_refresh():
    state.trigger(force=True)
    return {"ok": True}


@app.post("/api/pause")
async def api_pause(request: Request):
    """Pause the periodic check: {"minutes": N}; 0 = until resumed."""
    body = await json_dict(request)
    minutes = body.get("minutes", 0)
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






















































