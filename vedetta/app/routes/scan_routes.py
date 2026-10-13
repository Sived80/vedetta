"""scan_routes: moved out of main.py (see tools/split_module.py)."""
from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi import Request
from ..sse import SSE_HEADERS, _sse
import asyncio
from ..storage import blocklist, devices_config, journal, newdevices
from ..netutil import filter_local_ips
from ..applog import logger
from ..scan import pipeline
from .bodies import json_dict
from ..scan import scanner
from ..state import state


router = APIRouter()


_quick_scan: asyncio.Task | None = None


@router.post("/api/scan/quick")
async def api_scan_quick():
    """Only one search at a time: whoever requests it while one is running (even from another
    device) waits for the one already started and receives the same result."""
    global _quick_scan
    if _quick_scan is None or _quick_scan.done():
        _quick_scan = asyncio.create_task(_run_quick_scan())
    else:
        logger.info("Ricerca rapida gia' in corso: la richiesta si unisce a quella")
    # shield: if a client disconnects the search continues for the others.
    visible, ignored = await asyncio.shield(_quick_scan)
    return JSONResponse(visible, headers={"X-Ignored-Count": str(ignored)})


async def _run_quick_scan() -> tuple[list[dict], int]:
    state.search_started()
    try:
        known_ips = {d["ip"] for d in devices_config.load_devices()}
        hosts = await pipeline.run_initial()
        new_hosts = [
            {"ip": h["ip"], "mac": h["mac"], "hostname": h["hostname"], "already_added": False}
            for h in hosts
            if h["ip"] not in known_ips
        ]
        logger.info("Ricerca rapida: %d host visti, %d nuovi", len(hosts), len(new_hosts))
        journal.add("detail", "journal.quick", icon="magnify", seen=len(hosts), new=len(new_hosts))
        # The new-devices counter is realigned to what the search found.
        newdevices.sync_present({h["mac"] for h in hosts if h.get("mac")})
        state.set_new_devices(await asyncio.to_thread(newdevices.list_new))
        # Ignored ones are not shown; their count goes in the header.
        visible = [h for h in new_hosts if not blocklist.matches(mac=h["mac"], ip=h["ip"], name=h["hostname"])]
        return visible, len(new_hosts) - len(visible)
    finally:
        state.search_finished()


@router.post("/api/scan/deep")
async def api_scan_deep(request: Request):
    """Streaming (SSE): a 'progress' event for every device that has just finished
    being analyzed in depth, so the pop-up can show the real progress
    instead of a blind wait."""
    body = await json_dict(request)
    ips = await filter_local_ips([ip for ip in body.get("ips", []) if scanner.is_valid_ipv4(ip)])
    hints = body.get("hints") or {}

    # The jobs start here, not inside the generator: if the browser changes page
    # the stream is interrupted but the scans continue, and the activity stays
    # flagged until they really finish.
    state.search_started()
    tasks = pipeline.start_associative(ips, hints)
    all_done = asyncio.gather(*tasks, return_exceptions=True)
    all_done.add_done_callback(lambda _: state.search_finished())
    state.track(all_done)

    async def stream():
        total = len(ips)
        yield _sse({"type": "total", "total": total})
        results = []
        done = 0
        for task in asyncio.as_completed(tasks):
            result = await _finished(task)
            done += 1
            if result is _NO_RESULT:
                continue
            info = result.get("scan_info") or {}
            journal.add("detail", "journal.analyzed", icon="magnify", ip=result.get("ip", "?"),
                        ports=len(info.get("ports") or []))
            results.append(result)
            yield _sse({"type": "progress", "done": done, "total": total, "result": result})
        yield _sse({"type": "complete", "results": results})

    return StreamingResponse(stream(), media_type="text/event-stream", headers=SSE_HEADERS)


_NO_RESULT = object()


async def _finished(task):
    """The result of a search that has ended; _NO_RESULT if it failed or was cancelled. The closing of the stream itself goes on."""
    try:
        return await task
    except asyncio.CancelledError:
        me = asyncio.current_task()
        if me is not None and getattr(me, "cancelling", lambda: 0)():
            raise  # the stream itself is being closed, not a cancelled search
    except Exception:
        pass
    return _NO_RESULT


# What the search has learned about the device and that is worth keeping on adding
# (short texts): web, self-declarations (UPnP, mDNS, ONVIF, local interfaces), TLS/SSH.
SCAN_INFO_KEYS = ("http_title", "http_server", "mdns_name", "mdns_model", "mdns_manufacturer", "mdns_services",
                  "upnp_name", "upnp_manufacturer", "upnp_model", "netbios_name", "snmp_descr", "onvif_name",
                  "onvif_hardware", "onvif_manufacturer", "wsd_types", "rtsp_server", "tls_subject", "tls_issuer",
                  "ssh_hostkey", "api_source", "api_vendor", "api_model", "api_name", "api_fw", "igmp_groups")


@router.post("/api/scan/cancel")
async def api_scan_cancel(request: Request):
    """Cancel the associative searches in progress (all, or only the given IPs):
    the nmap processes are terminated, results already completed remain valid."""
    try:
        body = await request.json()
    except ValueError:
        body = {}
    ips = body.get("ips") if isinstance(body, dict) else None
    n = pipeline.cancel_associative(ips if isinstance(ips, list) else None)
    if n:
        journal.add("detail", "journal.cancelled", icon="close-circle", n=n)
    return {"cancelled": n}
