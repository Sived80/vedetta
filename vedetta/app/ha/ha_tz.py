"""Time zone (and language) of Home Assistant. The nightly maintenance (03:00) and the time written in the log are the user's own, read from
Home Assistant (WebSocket command get_config, with the read-only access the app already has). Without Home Assistant (or with
the access turned off) the container's own time zone is used."""
import json
import time
from datetime import datetime, tzinfo
from zoneinfo import ZoneInfo

from . import ha_registry
from .. import i18n
from ..applog import logger, set_zone_provider

REFRESH_S = 3600
RETRY_S = 300
_state: dict = {"zone": None, "at": 0.0}


def zone_from_config(config: dict | None) -> ZoneInfo | None:
    """The zone named in Home Assistant's configuration, None if missing or unknown."""
    name = (config or {}).get("time_zone")
    try:
        return ZoneInfo(name) if name else None
    except Exception:
        return None


def zone() -> tzinfo:
    return _state["zone"] or datetime.now().astimezone().tzinfo


set_zone_provider(zone)   # the log writes its times in this zone (applog does not import this module)


def now() -> datetime:
    return datetime.now(zone())


async def refresh(force: bool = False) -> bool:
    """Reads the time zone from Home Assistant (at most once an hour, five minutes after a failure). True if it changed."""
    if not force and time.time() - _state["at"] < REFRESH_S:
        return False
    _state["at"] = time.time()
    token = ha_registry.token()
    if not token:
        return False
    try:
        found = await _read_zone(token)
    except Exception as exc:
        _state["at"] = time.time() - REFRESH_S + RETRY_S
        logger.info("Fuso orario di Home Assistant non letto (%s): si usa quello del contenitore", type(exc).__name__)
        return False
    return _apply_zone(found)


async def _read_zone(token: str) -> ZoneInfo | None:
    """Connects to Home Assistant, sets the system language from its configuration and returns its time zone (None if it names none or an unknown one)."""
    import websockets
    async with websockets.connect(ha_registry.WS_URL, open_timeout=ha_registry.TIMEOUT_S) as ws:
        await _authenticate(ws, token)
        config = await _get_config(ws)
        i18n.set_system_language((config or {}).get("language"))   # the same answer tells the language of Home Assistant
        return zone_from_config(config)


async def _authenticate(ws, token: str) -> None:
    """The Home Assistant WebSocket greeting and login; raises if the server does not ask for authentication or refuses the token."""
    first = json.loads(await ws.recv())
    if first.get("type") != "auth_required":
        raise RuntimeError(f"unexpected answer: {first.get('type')}")
    await ws.send(json.dumps({"type": "auth", "access_token": token}))
    if json.loads(await ws.recv()).get("type") != "auth_ok":
        raise RuntimeError("authentication refused")


async def _get_config(ws) -> dict | None:
    """Asks for the configuration and waits for the answer to that request (other messages are skipped); None if the request failed."""
    await ws.send(json.dumps({"id": 1, "type": "get_config"}))
    while True:
        msg = json.loads(await ws.recv())
        if msg.get("id") == 1:
            return msg.get("result") if msg.get("success") else None


def _apply_zone(found: ZoneInfo | None) -> bool:
    """Stores the zone read from Home Assistant; True if it is different from the one in use."""
    if found is None:
        return False
    changed = str(_state["zone"]) != str(found)
    _state["zone"] = found
    if changed:
        logger.info("Fuso orario: %s (da Home Assistant)", found)
    return changed
