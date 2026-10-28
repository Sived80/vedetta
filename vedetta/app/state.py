"""The shared state of the service: DeviceState keeps the card of every device and drives the periodic check. The work itself is in state_cycle (the check and the online/offline decision)
and state_support (activities, presence, MAC shadow, diagnostics); DeviceState delegates to them."""
import asyncio
import time

from .formatters import update_generic_titles
from .storage import devices_config, newdevices, settings
from .scan import latency, presence, probe, touch_policy
from . import maclayer, name_origin, state_support, state_cycle
from .cyclestats import CycleStats
from .identity_upkeep import IdentityUpkeep
from .arpview import ArpView
from .newdevicewatch import NewDeviceWatch
from .eventbus import EventBus
from .pause import Pause
from .applog import logger
from .storage.history import history
from .storage import journal
import contextlib

# The check interval is a setting (settings.poll_interval, 10-300 s),
# re-read on every cycle: see _interval().
ARP_MAX_AGE = 10
# Between two automatic cycles at least this long, whoever wakes the loop (a changed address, merged cards, MQTT): an unbroken chain of
# wake-ups would otherwise ask the network without pause. A refresh asked by the user is never delayed.
MIN_GAP_S = 10.0
_PROCESS_START = time.time()
_MAX_TOMBSTONES = 200

# A device is reported offline only after this number of consecutive failed
# checks (~90s at a 30s interval). Phones in standby and devices with
# WiFi power saving occasionally skip a check: without this
# tolerance their cards changed state (and were replaced) on every cycle.
# The offline detection delay scales with the chosen interval (3 x interval).
MISS_LIMIT = 3

_OBSERVED = state_cycle.OBSERVED      # the fields kept from the last good check while a miss is tolerated (state_cycle.py)


def _ip_key(device: dict) -> tuple[int, ...]:
    return tuple(int(o) for o in device["ip"].split("."))


class DeviceState(IdentityUpkeep):
    """Device state kept in memory and updated by a background poller. Pages
    read it without doing synchronous probes, and every change
    is sent to open browsers as an event (SSE)."""

    def __init__(self) -> None:
        self.devices: dict[str, dict] = {}
        self.merged_total = 0                  # phone cards merged since the app started
        self.merge_report: dict | None = None  # what the last check decided: counts, never names
        self.rev = 0
        self.ready = asyncio.Event()
        # Last MAC seen per device: when powered off the probe no longer sees it,
        # but it is still needed to recognise its name and brand (DHCP fingerprint, prefix).
        self._last_mac: dict[str, str] = {}
        self._rev_of: dict[str, int] = {}
        self._removed: dict[str, int] = {}
        self._bus = EventBus()
        self._wake = asyncio.Event()
        self._force = False  # a manually requested refresh also applies while paused
        self._conflicts_reported: set = set()
        self._pause = Pause()
        self._task: asyncio.Task | None = None
        self._next_at = 0.0
        self._view = ArpView(lambda fresh: setattr(self._new, "baseline_blocks", tuple(set(self._new.baseline_blocks) | set(fresh))))
        self._cause = ""                  # why this cycle starts: "" = the timer, otherwise who woke the loop
        self._wake_reason = ""
        self._last_start = 0.0
        self._stats = CycleStats()
        self._bg: set[asyncio.Future] = set()
        self._presence = state_support.Presence(self._bg)      # who is online: misses, last seen, what the history last recorded (state_support.py)
        self._activity = state_support.Activity(lambda event: self.emit_event(event), lambda: self.rev)      # scans and searches in progress (state_support.py)
        self._new = NewDeviceWatch(lambda: self.devices, lambda e: self.emit_event(e), lambda *a, **k: self.emit_alert(*a, **k))

    # ---- lifecycle ----
    async def load_history(self) -> None:
        """Restarts from the saved state (state_support.py)."""
        await self._presence.load(history, self._last_mac)

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    def trigger(self, force: bool = False, reason: str = "") -> None:
        """Forces an immediate update cycle (force: even while paused). `reason` goes in the log if the cycles come in a chain."""
        if force:
            self._force = True
            self._view.last_full = None       # a refresh asked by hand asks the whole network again
        self._wake_reason = self._wake_reason or reason
        self._wake.set()

    # ---- pause of the periodic check ----
    def paused_remaining(self) -> float | None:
        """Seconds until the pause ends (inf = no expiry); None if not paused."""
        return self._pause.remaining()

    def pause(self, minutes: int = 0) -> None:
        """Suspends periodic checks for N minutes (0 = until resumed).
        Manually requested actions (refresh, search) remain possible."""
        self._pause.start(minutes)
        logger.info("Controllo periodico in pausa (%s)", f"{minutes} min" if minutes else "fino alla ripresa")
        self.emit_event(self.poll_info())
        self._wake.set()

    def resume(self) -> None:
        self._pause.stop()
        logger.info("Controllo periodico ripreso")
        self._force = True
        self.emit_event(self.poll_info())
        self._wake.set()

    # ---- reading ----
    def sorted_devices(self) -> list[dict]:
        return sorted(self.devices.values(), key=_ip_key)

    def poll_info(self) -> dict:
        interval = self._interval()
        next_in = max(0.0, self._next_at - time.monotonic()) if self._next_at else interval
        left = self.paused_remaining()
        return {
            "type": "poll", "rev": self.rev, "interval_ms": interval * 1000, "next_in_ms": int(next_in * 1000),
            "paused": left is not None,
            "paused_in_ms": int(left * 1000) if left is not None and left != float("inf") else None,
            "paused_total_ms": int(self._pause.total * 1000)
            if left is not None and left != float("inf") and self._pause.total else None,
        }

    @staticmethod
    def _miss_limit() -> int:
        """Consecutive failed checks before going offline (user setting)."""
        try:
            return settings.miss_limit()
        except Exception:
            return MISS_LIMIT

    @staticmethod
    def _interval() -> int:
        """Current interval in seconds (user setting)."""
        try:
            return settings.poll_interval()
        except Exception:
            return settings.DEFAULTS["poll_interval"]

    # ---- events ----
    def subscribe(self) -> asyncio.Queue:
        return self._bus.subscribe()

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._bus.unsubscribe(q)

    def is_subscribed(self, q: asyncio.Queue) -> bool:
        return self._bus.is_subscribed(q)

    # ---- activities in progress ----
    def track(self, future: asyncio.Future) -> None:
        """Holds a strong reference to a background job: a task without
        references can be garbage collected midway."""
        self._bg.add(future)
        future.add_done_callback(self._bg.discard)

    def activity_info(self) -> dict:
        return self._activity.info()

    def rescan_started(self, device_ids: list[str]) -> None:
        self._activity.rescan_started(device_ids)

    def rescan_finished(self, device_id: str) -> None:
        self._activity.rescan_finished(device_id)

    def search_started(self) -> None:
        self._activity.search_started()

    def search_finished(self) -> None:
        self._activity.search_finished()

    def emit_alert(self, log_message: str, key: str, **params) -> None:
        """Notice (e.g. new open port): to the log the text as is, to
        open browsers the key and parameters, translated into each one's language."""
        logger.warning(log_message)
        journal.add("normal", key, icon="alert", **params)
        self.emit_event({"type": "alert", "level": "warning", "key": key, "params": params})

    def emit_event(self, event: dict) -> None:
        """Event to open browsers (e.g. network roles updated), stamped with the current revision unless it has one."""
        event = {**event, "rev": self.rev} if "rev" not in event else event
        self._bus.publish(event)

    def catch_up(self, since: int) -> list[dict]:
        """Events missed by a client that fell behind (or just connected with the
        revision of the page it received)."""
        events = []
        for device_id, rev in self._rev_of.items():
            if rev > since and device_id in self.devices:
                events.append({"type": "device", "id": device_id, "rev": rev, "device": self.devices[device_id]})
        for device_id, rev in self._removed.items():
            if rev > since:
                events.append({"type": "removed", "id": device_id, "rev": rev})
        return events

    # ---- update ----
    async def arp_snapshot(self) -> dict[str, dict]:
        """Recent ARP table (reuses the one from the check cycle if fresh)."""
        return await self._view.by_ip(120)

    async def _arp_by_ip(self, max_age: float) -> dict[str, dict]:
        return await self._view.by_ip(max_age)

    def diagnostics(self) -> dict:
        """How the service is doing, for the export: sizes, times and counts, never an address or a name (state_support.py)."""
        return state_support.diagnostics(self, _PROCESS_START, history)

    # ---- how the cycles go (a line in the log, only when something is wrong, and one summary an hour) ----
    def _note_start(self, cause: str) -> None:
        self._stats.note_start(cause, MIN_GAP_S)

    def _note_end(self, started: float) -> None:
        self._stats.note_end(started, self._view.asked, self._view.found, self._view.plan_info)

    def _shadow(self, device_id: str, previous: dict | None, result: dict, now: float) -> None:
        """Data per MAC for later analysis and the judgement of the card (state_support.py). Never decides anything shown, never raises."""
        state_support.watch(device_id, previous, result, self._last_mac, now, self._bg, self.emit_alert)

    def _record_presence(self, result: dict, online: bool, ts: float) -> None:
        """Saves only online/offline transitions to the history (state_support.py)."""
        self._presence.record(history, result, online, ts)

    # the presence keeps these dictionaries; IdentityUpkeep and the tests read them here
    @property
    def _misses(self) -> dict[str, int]:
        return self._presence.misses

    @property
    def _last_seen(self) -> dict[str, float]:
        return self._presence.last_seen

    @property
    def _db_state(self) -> dict[str, bool]:
        return self._presence.db_state

    def _apply(self, config: dict, result: dict, current: dict[str, dict], sample: float | None = None,
               force: bool = False) -> None:
        """sample = response time measured in this cycle (ms, None if the
        measurement got no response)."""
        # If the device configuration changed while the probe was
        # running (rename, new scan...), the result is already stale:
        # applying it would briefly bring back the old name.
        if current.get(config["id"]) != config:
            return

        device_id = result["id"]
        auto = result.pop("auto_name", None)
        if auto:
            devices_config.update_auto_name(device_id, auto[0], auto[1], force=len(auto) > 2 and bool(auto[2]), mac=result.get("mac"))
        name_origin.remember(config, result.get("mac"))
        previous = self.devices.get(device_id)
        now = time.time()
        if result.get("mac"):
            if result["online"]:
                self._shadow(device_id, previous, result, now)
            self._last_mac[device_id] = result["mac"]
        state_cycle.publish(self, state_cycle.settle(self, device_id, result, previous, now, sample), force)

    def remove(self, device_id: str) -> None:
        if self.devices.pop(device_id, None) is None:
            return
        self._presence.forget(device_id)
        latency.tracker.reset(device_id)
        self.rev += 1
        self._rev_of.pop(device_id, None)
        self._removed[device_id] = self.rev
        while len(self._removed) > _MAX_TOMBSTONES:
            self._removed.pop(next(iter(self._removed)))
        self.emit_event({"type": "removed", "id": device_id})

    async def poll_once(self) -> None:
        await state_cycle.poll_once(self)

    async def _record_macs(self, arp: dict[str, dict]) -> None:
        await maclayer.record(arp, history)

    async def _save_latency(self) -> None:
        """One average sample per minute per device, in a single transaction."""
        rows = latency.tracker.take_minute()
        if not rows:
            return
        try:
            await asyncio.to_thread(history.record_latency, rows)
        except Exception:
            logger.exception("Salvataggio dello storico latenza fallito")

    # ---- new devices on the network ----
    def set_new_devices(self, devices: list[dict]) -> None:
        self._new.set(devices)

    async def new_devices_event(self) -> dict:
        """Event with the current list (initial frame of api_events)."""
        devices = await asyncio.to_thread(newdevices.list_new)
        return newdevices.event(devices)

    async def check_new_devices(self, arp: dict[str, dict] | None = None) -> None:
        if arp is None:
            arp = self._view.cache[1] if self._view.cache else {}
        await self._new.check(arp)

    async def refresh_device(self, device_id: str, force: bool = False) -> None:
        """Immediately updates a single device (after an edit or a
        scan), without waiting for the next cycle."""
        all_configs = devices_config.load_devices()
        update_generic_titles(all_configs)
        config = next((c for c in all_configs if c["id"] == device_id), None)
        if config is None:
            self.remove(device_id)
            return
        arp_task = asyncio.create_task(self._arp_by_ip(ARP_MAX_AGE))
        result, sample = await asyncio.gather(
            probe.probe_device({**config, "last_mac": self._last_mac.get(device_id), **presence.mac_view(self._last_mac)}, arp_task),
            self._measure(config),
        )
        current = {c["id"]: c for c in devices_config.load_devices()}
        self._apply(config, result, current, sample, force=force)

    @staticmethod
    async def _measure(config: dict) -> float | None:
        """The response time of the device, unless it must not be touched (touch_policy)."""
        return await latency.measure(config["ip"], config.get("port", 80)) if touch_policy.may_touch(config) else None

    async def _loop(self) -> None:
        await state_cycle.loop(self, MIN_GAP_S)


state = DeviceState()
