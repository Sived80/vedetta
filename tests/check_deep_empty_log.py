"""The log of a deep search that finds nothing to keep (scan/rescan.py _run_deep_scan). A phone whose only open ports are dynamic ones (an iPhone: 62078 and the like, never kept) has no result worth saving
at every search: that is normal and says INFO; it says WARNING only when the card had real ports before and now there is none (a device that went quiet or is filtered). The time in the line is the
elapsed time and, when the device waited for nmap, how much of it was work (a search starts all its devices together: "scanned in 352 s" was 9 s of work)."""
import asyncio
import logging
import os
import sys
import tempfile
import time

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import rescan, work_time  # noqa: E402

LOG = []
rescan.logger.log = lambda level, msg, *a: LOG.append((logging.getLevelName(level), msg % a))
rescan.devices_config.update_scan_info = lambda *a, **k: None
rescan.touch_policy.touch_level = lambda device: None
rescan.scanner.format_scan_info = lambda info: info.get("fields", {})
WORK = {"sleep": 0.0, "run": 0.0}


async def fake_deep(ip, batch, slow=False):
    await asyncio.sleep(WORK["sleep"])
    now = time.monotonic()
    work_time.note(now - WORK["run"], now)
    return {"fields": {}}


rescan.pipeline.run_deep = fake_deep


def deep(ports):
    device = {"id": "d", "ip": "10.0.0.5", "name": "Phone", "scan_info": {"ports": [{"label": str(p)} for p in ports]}}
    LOG.clear()
    result = asyncio.run(rescan._run_deep_scan(device, None))
    return result, list(LOG)


# --- only dynamic ports before (the phone): normal, INFO, and the card is marked as searched
result, log = deep([53691, 56381, 62078])
assert result[0] == {} and len(log) == 1 and log[0][0] == "INFO", log
assert "10.0.0.5 (Phone) scansione completata senza alcun risultato utile" in log[0][1] and "dati precedenti mantenuti" in log[0][1], log
# --- no ports before at all: also normal
assert deep([])[1][0][0] == "INFO"
# --- real ports before and nothing now: this one is worth a WARNING
assert deep([80, 62078])[1][0][0] == "WARNING"
assert deep([22])[1][0][0] == "WARNING"
# --- the edge: 49152 and up are dynamic (the older rule), 49151 is a port like any other
assert deep([49152])[1][0][0] == "INFO" and deep([49151])[1][0][0] == "WARNING"

# --- the time: with no wait one number; with a wait the work next to it
WORK.update(sleep=0.0, run=0.0)
assert "(0s)" in deep([])[1][0][1], deep([])[1][0][1]
WORK.update(sleep=3.0, run=2.0)
assert "(3s, di cui 2s di lavoro)" in deep([])[1][0][1], deep([])[1][0][1]
print("check_deep_empty_log OK")
