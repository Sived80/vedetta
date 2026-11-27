# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The Sentinel's way out of the browser (step 3): what sentinel_view sends at the end of a cycle reaches Home Assistant.

Two channels, through the Supervisor's WebSocket proxy (the same one the registry reads, ha_registry):
  - an EVENT on the bus of Home Assistant for every message: vedetta_new_device, vedetta_device_down, vedetta_device_back, with
    {card, label, ip} (and "minutes" for a return) and always {brand, type, kind, reason}: the product brand, the group (as the MQTT
    "type"), the finer type (as the MQTT "kind": "accesspoint", "nas", "tv"...) and, for a new device, why it is new (NEW_REASONS:
    "new_mac" = a MAC never seen on the home network, "new_behind_router" = an address never seen on a network behind the router).
    A value Vedetta does not know (or an event saved by an older version) is null, never absent, so templates stay simple; reason is
    null on a down or a back. An automation or a blueprint (blueprints/automation/vedetta) can act on it. Off until the person turns
    it on ("ha_events", decision A of 19/11: nothing is written to Home Assistant by default);
  - a NOTIFICATION to the recipients the person put in order ("notify_order": e.g. first notify.mobile_app_phone, then 30 s later
    notify.living_room_tv): one message per cycle, one line per event, in the language of Home Assistant, handed out by notify_queue
    (in line, each recipient after its wait, whether the one before took it or not). Off until a recipient is chosen.
Nothing leaves the house: the WebSocket goes to the Supervisor, Home Assistant does the rest. Outside Home Assistant (no token)
nothing is sent and nothing is an error. A failure is said once in the log, not at every cycle; test() reports it to the page."""
import asyncio
import json

from .. import i18n
from ..applog import logger
from ..storage import settings
from . import ha_registry, notify_queue

EVENT_TYPES = {"new": "vedetta_new_device", "down": "vedetta_device_down", "back": "vedetta_device_back"}
ALERT_KEYS = {"new": "alert.new_device", "down": "alert.device_down", "back": "alert.device_back"}
NEW_MAC, NEW_BEHIND_ROUTER = "new_mac", "new_behind_router"
NEW_REASONS = (NEW_MAC, NEW_BEHIND_ROUTER)
DETAIL_KEYS = ("brand", "type", "kind", "reason")
TITLE = "Vedetta"
_failed_once: set = set()
_tasks: set = set()


def lines(events: list[dict], lang: str) -> list[str]:
    """Pure: one translated line per event, the same words as the journal; a new device adds what it is (_facts_suffix)."""
    out = []
    for ev in events:
        key = ALERT_KEYS.get(ev.get("kind"))
        if not key:
            continue
        p = ev.get("params") or {}
        params = {"label": p.get("label") or ev.get("card"), "ip": p.get("ip") or "-"}
        if ev["kind"] == "back":
            params["minutes"] = max(1, round((p.get("away_s") or 0) / 60))
        suffix = _facts_suffix(p, lang) if ev["kind"] == "new" else ""
        out.append(i18n.translate(lang, key, **params) + suffix)
    return out


def _facts_suffix(p: dict, lang: str) -> str:
    """" · brand · type" for a new device: the finer type by its translated name, else the group's name, else nothing; what is not
    known is left out (an event saved by 1.0.2 gives the line of 1.0.2)."""
    kind_name = i18n.translate_or(lang, "kind." + p["kind"], "") if p.get("kind") else ""
    type_name = kind_name or (i18n.translate_or(lang, "group." + p["type"], "") if p.get("type") else "")
    parts = [part for part in (p.get("brand"), type_name) if part]
    return "".join(" · " + part for part in parts)


def event_data(ev: dict) -> dict:
    """Pure: the data of the event on the bus of Home Assistant (numbers and short texts only): the keys of DETAIL_KEYS always, null
    when not known."""
    p = ev.get("params") or {}
    data = {"card": ev.get("card"), "label": p.get("label") or ev.get("card"), "ip": p.get("ip") or "-",
            **{key: p.get(key) or None for key in DETAIL_KEYS}}
    if ev.get("kind") == "back":
        data["minutes"] = max(1, round((p.get("away_s") or 0) / 60))
    return data


def commands(events: list[dict], ha_events: bool, service: str, lang: str) -> list[dict]:
    """Pure: the WebSocket commands for one cycle (without their ids): an event per message, then one notification for all."""
    cmds = []
    if ha_events:
        cmds += [{"type": "fire_event", "event_type": EVENT_TYPES[ev["kind"]], "event_data": event_data(ev)}
                 for ev in events if ev.get("kind") in EVENT_TYPES]
    text = lines(events, lang)
    if service and text:
        cmds.append(_notify(service, "\n".join(text)))
    return cmds


def _notify(service: str, message: str) -> dict:
    domain, _, name = service.partition(".")
    return {"type": "call_service", "domain": domain, "service": name, "service_data": {"title": TITLE, "message": message}}


def sender(events: list[dict]) -> None:
    """For sentinel_view.add_sender: the sending runs in the background, the cycle does not wait for Home Assistant."""
    cfg = settings.sentinel_load()
    lang = i18n.normalize(i18n.system_language())
    cmds = commands(events, bool(cfg.get("ha_events")), "", lang)
    if not ha_registry.token():
        return
    if cmds:
        task = asyncio.create_task(_send_quietly(cmds))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    notify_queue.put("\n".join(lines(events, lang)), cfg["notify_order"], send_one)


async def send_one(service: str, message: str) -> None:
    """One notification to one recipient (for notify_queue)."""
    await send([_notify(service, message)])


async def _send_quietly(cmds: list[dict]) -> None:
    try:
        await send(cmds)
        _failed_once.clear()
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"[:200]
        if reason not in _failed_once:
            _failed_once.add(reason)
            logger.warning("Avvisi verso Home Assistant non inviati (%s)", reason)


async def send(cmds: list[dict]) -> None:
    """Sends the commands on one WebSocket, each one even after a refusal (events refused must not stop the notification);
    then RuntimeError with the first refusal (e.g. a service that does not exist)."""
    import websockets
    tok = ha_registry.token()
    if not tok:
        raise RuntimeError(ha_registry.missing_token())
    async with websockets.connect(ha_registry.ws_url(), open_timeout=ha_registry.TIMEOUT_S) as ws:
        await ha_registry._authenticate(ws, tok)
        refusals = [await _refusal(ws, number, cmd) for number, cmd in enumerate(cmds, start=1)]
    refused = next((r for r in refusals if r), None)
    if refused:
        raise refused


async def _refusal(ws, number: int, cmd: dict) -> RuntimeError | None:
    """Sends one command; its refusal, or None."""
    await ws.send(json.dumps({"id": number, **cmd}))
    try:
        await _result(ws, number, cmd["type"])
    except RuntimeError as exc:
        return exc
    except asyncio.TimeoutError:          # a slow answer refuses this command only: the next ones (the notification) still go (18/11 review)
        return RuntimeError(f"{cmd['type']}: no answer in {ha_registry.TIMEOUT_S} s")
    return None


async def _answer(ws, number: int) -> dict:
    """The answer with this id (events that arrive in between are skipped)."""
    while True:
        msg = json.loads(await asyncio.wait_for(ws.recv(), ha_registry.TIMEOUT_S))
        if msg.get("id") == number:
            return msg


async def _result(ws, number: int, what: str) -> None:
    msg = await _answer(ws, number)
    if not msg.get("success"):
        error = msg.get("error") or {}
        raise RuntimeError(f"{what}: {error.get('code') or ''} {error.get('message') or ''}".strip())


async def notify_services() -> list[str]:
    """The notify services Home Assistant has now ("notify.mobile_app_phone", ...), sorted; [] outside Home Assistant or on error."""
    import websockets
    tok = ha_registry.token()
    if not tok:
        return []
    try:
        async with websockets.connect(ha_registry.ws_url(), max_size=16 * 1024 * 1024, open_timeout=ha_registry.TIMEOUT_S) as ws:
            await ha_registry._authenticate(ws, tok)
            await ws.send(json.dumps({"id": 1, "type": "get_services"}))
            msg = await _answer(ws, 1)
    except Exception as exc:
        logger.info("Servizi di notifica non letti (%s)", f"{type(exc).__name__}: {exc}"[:200])
        return []
    return services_of(msg)


def services_of(msg: dict) -> list[str]:
    """Pure: the notify services in an answer of get_services (only names that settings accepts)."""
    result = (msg or {}).get("result") or {}
    names = (result.get("notify") or {}) if isinstance(result, dict) else {}
    return sorted(f"notify.{n}" for n in names if settings.sentinel_valid("notify_service", f"notify.{n}"))


async def test(service: str | None = None) -> dict:
    """The tests of the page. With a service (the «Try» of one row): a test notification to it at once, {"ok", "error"?}.
    Without (the «Send a test» of the window): a test event at once (only with the events on) and a test message in line for the whole
    order, with its waits; {"ok" (the event), "error"?, "queued": recipients}."""
    if not ha_registry.token():
        return {"ok": False, "error": "no_home_assistant"}
    message = i18n.translate(i18n.normalize(i18n.system_language()), "notify.test")
    if service:
        last = await notify_queue.try_now(send_one, service, message)
        return {"ok": True} if last["ok"] else {"ok": False, "error": last["error"]}
    cfg = settings.sentinel_load()
    order = cfg["notify_order"]
    result: dict = {"ok": True}
    if cfg.get("ha_events"):           # the test event only when the events are on: nothing is written to Home Assistant by default (19/11 review)
        try:
            await send([{"type": "fire_event", "event_type": "vedetta_test", "event_data": {"card": "test"}}])
        except Exception as exc:
            result = {"ok": False, "error": f"{exc}"[:200]}
    notify_queue.put(message, order, send_one)
    return {**result, "queued": len(order)}
