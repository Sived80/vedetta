"""Whether Home Assistant has a newer version of this add-on: the red dot on the menu button and the arrow in the menu.

Read-only. The add-on asks the Supervisor for its OWN card (/addons/self/info: the same call that run.sh already makes for the port), which says the
installed version, the latest one and whether an update is available. No new permission (the self endpoints are open to every add-on except
`update` and `security`), no call to the internet (the Supervisor already knows the latest version) and no guessing which entity is ours.
Asked at start and then every ten minutes; a Supervisor that is down or slow keeps the last answer and is asked again in two minutes. The page only
reads the answer kept here (see routes/ha.py): it never waits for the Supervisor."""
import asyncio
import os

from ..applog import logger
from . import ha_registry

SUPERVISOR_URL = os.environ.get("VEDETTA_SUPERVISOR_URL", "http://supervisor")
REFRESH_S = 600
RETRY_S = 120
TIMEOUT_S = 8
_value: dict | None = None
_task: asyncio.Task | None = None


def parse(info) -> dict | None:
    """The card of the add-on as {available, installed, latest}; None when it does not say its version."""
    if not isinstance(info, dict) or not info.get("version"):
        return None
    return {"available": bool(info.get("update_available")), "installed": str(info["version"]), "latest": str(info.get("version_latest") or "")}


def snapshot() -> dict | None:
    """The last answer (None: not known yet, or outside Home Assistant)."""
    return _value


async def _fetch(tok: str) -> dict:
    import httpx
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        reply = await client.get(SUPERVISOR_URL + "/addons/self/info", headers={"Authorization": "Bearer " + tok})
        reply.raise_for_status()
        return (reply.json() or {}).get("data") or {}


async def refresh() -> int:
    """Asks the Supervisor once; returns the seconds to wait before the next time."""
    global _value
    tok = ha_registry.token()
    if not tok:
        return RETRY_S
    try:
        info = await asyncio.wait_for(_fetch(tok), TIMEOUT_S)
    except Exception as exc:   # Supervisor down, slow or refusing: the dot simply does not change
        logger.info("Scheda dell'add-on non letta dal Supervisor (%s: %s)", type(exc).__name__, exc)
        return RETRY_S
    _value = parse(info)
    return REFRESH_S


async def _loop() -> None:
    while True:
        await asyncio.sleep(await refresh())


def start() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())


async def stop() -> None:
    if _task:
        _task.cancel()
