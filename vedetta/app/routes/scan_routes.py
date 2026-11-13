"""scan_routes: moved out of main.py (see tools/split_module.py)."""
from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi import Request
from ..sse import SSE_HEADERS, _sse
import asyncio
import time
from ..storage import blocklist, devices_config, journal, newdevices
from ..networks import registry
from ..applog import logger
from ..scan import pipeline
from .. import inventory_view, maclayer
from ..storage.history import history
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
    """1.0 step P9 (decisions 1A, 2A): a pass over the whole network now, written in the MAC layer like the pass of the cycle, then the
    inventory: what answered now and the devices confirmed or asleep that are not cards (inventory_view.listable), "seen X ago" for
    the ones asleep. The counter of new devices is not narrowed to what the pass heard any more: it is the same inventory."""
    state.search_started()
    try:
        hosts = await pipeline.run_initial()
        own = newdevices.own_macs()      # this computer is not a device of the network for the MAC layer
        await maclayer.observe_pass({h["ip"]: {"mac": h["mac"]} for h in hosts if newdevices.normalize_mac(h["mac"]) not in own}, history)
        rows = inventory_view.listable(hosts, devices_config.load_devices(), time.time())
        names = await asyncio.to_thread(_known_names)
        found = [{"ip": r["ip"], "mac": r["mac"], "hostname": r["hostname"] or names.get(str(r["mac"]).upper()),
                  "already_added": False, "last_seen": r["last_seen"]} for r in rows]
        logger.info("Ricerca rapida: %d host visti, %d da mostrare", len(hosts), len(found))
        journal.add("detail", "journal.quick", icon="magnify", seen=len(hosts), new=len(found))
        state.set_new_devices(await asyncio.to_thread(newdevices.list_new))
        # Ignored ones are not shown; their count goes in the header.
        visible = [h for h in found if not blocklist.matches(mac=h["mac"], ip=h["ip"], name=h["hostname"])]
        return visible, len(found) - len(visible)
    finally:
        state.search_finished()


def _known_names() -> dict[str, str]:
    """MAC -> the DHCP name already heard (the table of known MACs), for the devices the inventory lists without one."""
    return {str(m).upper(): r["hostname"] for m, r in history.known_all().items() if r.get("hostname")}


@router.post("/api/scan/deep")
async def api_scan_deep(request: Request):
    """Streaming (SSE): a 'progress' event for every device that has just finished
    being analyzed in depth, so the pop-up can show the real progress
    instead of a blind wait."""
    body = await json_dict(request)
    ips = await registry.allowed([ip for ip in body.get("ips", []) if scanner.is_valid_ipv4(ip)])
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
    except Exception:  # noqa: S110  the end of the stream of a search: nothing left to tell
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
