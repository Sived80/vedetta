"""Reads the devices that Home Assistant sees (ha_trackers) while the function is on, keeps them (passive_store) and writes their presence into the history.

Nothing here talks to a device: the only source is Home Assistant. When the function is off the loop does nothing (it does not even ask Home Assistant). A failed reading changes nothing but the error, and is not an
error for the user: the adopted devices simply keep their last known state."""
import asyncio
import contextlib
import time

from ..applog import logger
from ..storage import passive_store
from ..storage.history import history
from . import ha_trackers

REFRESH_S = 60
IDLE_S = 20
_task: asyncio.Task | None = None
_on_change = None
_last_online: dict[str, bool] = {}     # the presence last written to the history, by device id: only a change is written
_lock = asyncio.Lock()


def presence_changes(adopted: dict, last: dict) -> list[tuple]:
    """(id, ip, mac, online) of the adopted devices whose presence differs from the one last written (pure)."""
    out = []
    for mac, item in adopted.items():
        row = item["row"]
        did = passive_store.id_of(mac)
        online = bool(row.get("online"))
        if last.get(did) != online:
            out.append((did, row.get("ip"), mac.upper(), online))
    return out


def _write_presence(data: dict, ts: float) -> None:
    if not _last_online:
        _last_online.update({k: bool(v[0]) for k, v in history.last_presence().items() if passive_store.is_passive_id(k)})
    for did, ip, mac, online in presence_changes(data["adopted"], _last_online):
        history.record_presence(did, ip, mac, online, ts)
        _last_online[did] = online


async def read_now() -> dict:
    """One reading, now (the loop and the button "Read now" use it); returns the store as it is after it. Only one reading at a time."""
    async with _lock:
        ts = time.time()
        try:
            rows = await ha_trackers.fetch()
            error = None
        except Exception as exc:   # Home Assistant down, no permission, a token missing outside HA: told in the panel, never an error for the user
            rows, error = [], f"{type(exc).__name__}: {exc}"[:200]
            logger.info("Dispositivi visti da Home Assistant non letti (%s)", error)
        await asyncio.to_thread(passive_store.record_read, rows, ts, error)
        data = await asyncio.to_thread(passive_store.snapshot)
        if error is None:
            await asyncio.to_thread(_write_presence, data, ts)
            logger.info("Dispositivi visti da Home Assistant: %d letti, %d adottati", len(rows), len(data["adopted"]))
        if _on_change:
            _on_change({"type": "passive"})
        return data


async def _loop() -> None:
    while True:
        if not passive_store.enabled():
            await asyncio.sleep(IDLE_S)
            continue
        await read_now()
        await asyncio.sleep(REFRESH_S)


def start(on_change=None) -> None:
    global _task, _on_change
    _on_change = on_change
    if ha_trackers.ha_registry.token() and (_task is None or _task.done()):
        _task = asyncio.create_task(_loop())


async def stop() -> None:
    if _task:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _task
