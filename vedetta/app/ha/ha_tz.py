"""Time zone (and language) of Home Assistant. The nightly maintenance (03:00) and the time written in the log are the user's own, read from
Home Assistant (WebSocket command get_config, with the read-only access the app already has). Without Home Assistant (or with
the access turned off) the container's own time zone is used."""
import json
import time
from datetime import datetime, tzinfo
from zoneinfo import ZoneInfo

from . import ha_registry
from .. import i18n
from ..applog import logger

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
        import websockets
        async with websockets.connect(ha_registry.WS_URL, open_timeout=ha_registry.TIMEOUT_S) as ws:
            first = json.loads(await ws.recv())
            if first.get("type") != "auth_required":
                raise RuntimeError(f"unexpected answer: {first.get('type')}")
            await ws.send(json.dumps({"type": "auth", "access_token": token}))
            if json.loads(await ws.recv()).get("type") != "auth_ok":
                raise RuntimeError("authentication refused")
            await ws.send(json.dumps({"id": 1, "type": "get_config"}))
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("id") == 1:
                    config = msg.get("result") if msg.get("success") else None
                    i18n.set_system_language((config or {}).get("language"))   # the same answer tells the language of Home Assistant
                    found = zone_from_config(config)
                    break
    except Exception as exc:
        _state["at"] = time.time() - REFRESH_S + RETRY_S
        logger.info("Fuso orario di Home Assistant non letto (%s): si usa quello del contenitore", type(exc).__name__)
        return False
    if found is None:
        return False
    changed = str(_state["zone"]) != str(found)
    _state["zone"] = found
    if changed:
        logger.info("Fuso orario: %s (da Home Assistant)", found)
    return changed
