import asyncio
import time
from datetime import datetime

from .storage import devices_config
from .ha import ha_tz
from .scan import pipeline
from .applog import logger
from .storage.history import history
from .netutil import filter_local_ips
from .scan.rescan import rescan_device

NIGHT_HOUR = 3    # local time of Home Assistant (ha_tz)
STALE_DAYS = 7


def last_deep_attempt(device: dict) -> float:
    """When the deep search last ran on the device: a real result (scanned_at) or an attempt that found nothing."""
    info = device.get("scan_info") or {}
    return max(info.get("scanned_at", 0) or 0, info.get("deep_empty_at", 0) or 0)


async def run_nightly() -> None:
    """Rescan devices with data older than STALE_DAYS (or never
    scanned), one at a time so as not to compete for the container's CPU."""
    cutoff = time.time() - STALE_DAYS * 86400
    stale = [
        d for d in devices_config.load_devices()
        if last_deep_attempt(d) < cutoff
    ]
    local = set(await filter_local_ips([d["ip"] for d in stale])) if stale else set()
    stale = [d for d in stale if d["ip"] in local]
    logger.info("Manutenzione notturna: %d dispositivi da riscansionare", len(stale))

    if stale:
        # Batch functions of the deep profile (mDNS, SSDP...) run only once.
        batch = await pipeline.prepare_batch("deep", [d["ip"] for d in stale])
        for device in stale:
            try:
                await rescan_device(device, batch)
            except Exception:
                logger.exception("Manutenzione notturna: scansione fallita per %s", device["ip"])

    removed = await asyncio.to_thread(history.prune)
    logger.info("Manutenzione notturna completata (%d eventi vecchi rimossi dallo storico)", removed)

    # MAC prefix database: if automatic update is enabled, every 30 days.
    try:
        from .recognition import oui_update
        if await asyncio.to_thread(oui_update.auto_update_enabled) and await asyncio.to_thread(oui_update.is_due):
            await asyncio.to_thread(oui_update.update)
    except Exception as exc:
        logger.warning("Manutenzione notturna: aggiornamento prefissi MAC non riuscito (%s)", exc)


def is_night(now: datetime) -> bool:
    return now.hour == NIGHT_HOUR


async def nightly_loop() -> None:
    while True:
        await asyncio.sleep(60)
        try:
            await ha_tz.refresh()
            now = ha_tz.now()
            if not is_night(now):
                continue
            today = now.date().isoformat()
            if await asyncio.to_thread(history.meta_get, "last_nightly") == today:
                continue
            # Marked before starting: a restart during the night does not redo it.
            await asyncio.to_thread(history.meta_set, "last_nightly", today)
            await run_nightly()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Manutenzione notturna fallita")
