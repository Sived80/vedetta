import asyncio
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from . import devices_config, pipeline
from .applog import logger
from .history import history
from .netutil import filter_local_ips
from .rescan import rescan_device

TZ = ZoneInfo("Europe/Rome")
NIGHT_HOUR = 3
STALE_DAYS = 7


async def run_nightly() -> None:
    """Rescan devices with data older than STALE_DAYS (or never
    scanned), one at a time so as not to compete for the container's CPU."""
    cutoff = time.time() - STALE_DAYS * 86400
    stale = [
        d for d in devices_config.load_devices()
        if (d.get("scan_info") or {}).get("scanned_at", 0) < cutoff
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
        from . import oui_update
        if await asyncio.to_thread(oui_update.auto_update_enabled) and await asyncio.to_thread(oui_update.is_due):
            await asyncio.to_thread(oui_update.update)
    except Exception as exc:
        logger.warning("Manutenzione notturna: aggiornamento prefissi MAC non riuscito (%s)", exc)


async def nightly_loop() -> None:
    while True:
        await asyncio.sleep(60)
        try:
            now = datetime.now(TZ)
            if now.hour != NIGHT_HOUR:
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
