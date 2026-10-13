"""What DeviceState keeps and reports besides the cards, in four small parts: the activities in progress (scans and searches, kept here and not only in the browser that started them, so that after changing page
the blinking LED and the search button are found as they were), who is online (presence), the MAC shadow jobs, and the numbers of the diagnostics for the export."""
import asyncio
import time
from .applog import logger
from .export import mac_shadow
from .ha import identity_shift
from .storage import settings
import ipaddress
from . import lifecycle, maclayer, procfs
from .scan import dhcp


class Activity:
    def __init__(self, emit, get_rev) -> None:
        self.rescanning: set[str] = set()
        self.search_running = 0
        self.search_hold_until = 0.0
        self._emit = emit
        self._get_rev = get_rev

    def info(self) -> dict:
        searching = self.search_running > 0 or time.monotonic() < self.search_hold_until
        return {"type": "activity", "rev": self._get_rev(), "rescanning": sorted(self.rescanning), "search": searching}

    def _emit_activity(self) -> None:
        self._emit(self.info())

    def rescan_started(self, device_ids: list[str]) -> None:
        self.rescanning.update(device_ids)
        self._emit_activity()

    def rescan_finished(self, device_id: str) -> None:
        self.rescanning.discard(device_id)
        self._emit_activity()

    def search_started(self) -> None:
        self.search_running += 1
        self._emit_activity()

    def search_finished(self) -> None:
        self.search_running = max(0, self.search_running - 1)
        # The search is made of two requests (quick, then in-depth): a short
        # hold keeps the effect from switching off and on again between the two.
        self.search_hold_until = time.monotonic() + 2.5
        self._emit_activity()
        asyncio.get_running_loop().call_later(2.6, self._emit_activity)


# --- Who is online: the consecutive failed checks, when each device was last seen online and what the history last recorded of it (was py)

class Presence:
    def __init__(self, background: set) -> None:
        self.misses: dict[str, int] = {}
        self.last_seen: dict[str, float] = {}
        self.db_state: dict[str, bool] = {}
        self._background = background      # the set that keeps the writing tasks alive

    async def load(self, history, last_mac: dict) -> None:
        """Restarts from the saved state: without it, after every restart the "last seen" of offline devices would be lost."""
        try:
            last = await asyncio.to_thread(history.last_presence)
        except Exception:
            logger.exception("Lettura dello storico presenza fallita")
            return
        for device_id, (online, ts) in last.items():
            self.db_state[device_id] = online
            if not online:
                self.last_seen[device_id] = ts
            mac = await asyncio.to_thread(history.last_mac, device_id)
            if mac:
                last_mac[device_id] = mac

    def record(self, history, result: dict, online: bool, ts: float) -> None:
        """Saves only online/offline transitions to the history."""
        device_id = result["id"]
        if self.db_state.get(device_id) == online:
            return
        self.db_state[device_id] = online
        task = asyncio.create_task(self._write(history, device_id, result.get("ip"), result.get("mac"), online, ts))
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def _write(self, history, device_id: str, ip: str | None, mac: str | None, online: bool, ts: float) -> None:
        try:
            await asyncio.to_thread(history.record_presence, device_id, ip, mac, online, ts)
        except Exception:
            logger.exception("Salvataggio dello storico presenza fallito per %s", device_id)

    def forget(self, device_id: str) -> None:
        self.misses.pop(device_id, None)
        self.last_seen.pop(device_id, None)
        self.db_state.pop(device_id, None)


# --- Data per MAC for later analysis (export/mac_shadow.py) and the judgement of a card: two different devices behind it? (ha/identity_shift.py) (was py)

def watch(device_id: str, previous: dict | None, result: dict, last_mac: dict, now: float, background: set, emit_alert) -> None:
    """Data per MAC for later analysis. Never decides anything shown, never raises. `background` is the set that keeps the tasks alive."""
    try:
        job = mac_shadow.observe(device_id, previous, result, last_mac.get(device_id), now)
        judge = identity_shift.due(device_id, (result.get("mac") or "").lower(), now)
        if job or judge:
            task = asyncio.create_task(_job(device_id, job, result if judge else None, last_mac, now, emit_alert))
            background.add(task)
            task.add_done_callback(background.discard)
    except Exception:
        logger.debug("mac_shadow failed for %s", device_id, exc_info=True)


async def _job(device_id: str, job, judge_result: dict | None, last_mac: dict, now: float, emit_alert) -> None:
    """The memory per MAC is written first (a thread); then, if it is time, the card is judged."""
    try:
        if job:
            await asyncio.to_thread(job)
        if judge_result is not None:
            found = await asyncio.to_thread(identity_shift.evaluate, device_id, judge_result.get("mac"), dict(last_mac), now)
            _announce(found, judge_result, emit_alert)
    except Exception:
        logger.debug("shadow job failed for %s", device_id, exc_info=True)


def _announce(found: dict | None, judge_result: dict, emit_alert) -> None:
    """A new other device behind the card is told to the user (if alerts are on)."""
    if found and found["new"] and settings.alerts_enabled():
        name = judge_result.get("name") or judge_result.get("ip")
        other = identity_shift.describe(found)
        emit_alert("Dietro %s rispondono due dispositivi diversi: %s" % (name, other), "alert.other_device", name=name, other=other)


# --- DeviceState.diagnostics: how the service is doing, for the export (was py)

def diagnostics(state, process_start: float, history) -> dict:
    out: dict = {"uptime_s": int(time.time() - process_start), "interval_s": state._interval(), "paused": state.paused_remaining() is not None,
                 "devices": len(state.devices)}
    network = _network_info(state._view)
    if network is not None:
        out["network"] = network
    out["arp"] = {"addresses_asked": state._view.asked, "hosts_found": state._view.found}
    mac_layer = _mac_layer_info(history)
    if mac_layer is not None:
        out["mac_layer"] = mac_layer
    out["cycles"] = {"since_start": state._stats.total_cycles, "slowest_s": round(state._stats.slowest, 1),
                     "chains": state._stats.total_chains, "last_hour": state._stats.last_summary}
    out.update(_process_info())
    if lifecycle.previous:
        out["previous_run"] = dict(lifecycle.previous)          # how the previous run ended (clean or not, and the first suspect)
    return out


def _network_info(view) -> dict | None:
    """The size of the network and how it is searched, or None when it is not known (or not valid)."""
    try:
        if not view.net:
            return None
        net = ipaddress.ip_network(view.net[1], strict=False)
        info = {"prefix": net.prefixlen, "addresses": net.num_addresses, "mode": "blocks" if view.plan_info else "whole"}
        if view.plan_info:
            info.update({"blocks_total": view.plan_info["total"], "blocks_done": view.plan_info["done"]})
        return info
    except ValueError:
        return None


def _mac_layer_info(history) -> dict | None:
    try:
        return {**history.maclayer_summary(), **maclayer.observation_report(history, dhcp.seen)}
    except Exception:
        logger.exception("Riepilogo del livello MAC non disponibile")
        return None


def _process_info() -> dict:
    """Memory and threads of the process (Linux only: nothing where the file does not exist)."""
    out: dict = {}
    try:
        for line in procfs.lines("/proc/self/status"):
            if line.startswith(("VmRSS:", "Threads:")):
                key, value = line.split(":", 1)
                out["rss_mb" if key == "VmRSS" else "threads"] = int(value.split()[0]) // (1024 if key == "VmRSS" else 1)
    except ValueError:         # a bad number ends the reading and keeps what was read
        pass
    return out
