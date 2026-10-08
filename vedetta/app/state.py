import asyncio
import json
import time

from .formatters import update_generic_titles
from .storage import blocklist, devices_config, newdevices, settings
from .scan import dhcp, latency, probe, scanner
from .export import mac_shadow
from .ha import identity_shift
from . import netutil
from .applog import logger
from .storage.history import history

# The check interval is a setting (settings.poll_interval, 10-300 s),
# re-read on every cycle: see _interval().
ARP_MAX_AGE = 10
_MAX_TOMBSTONES = 200
_QUEUE_SIZE = 200
# Two cards of the same phone (it changed IP and private MAC): merged only if their names are the same and the two were
# never online together for longer than this (the 3 failed checks of tolerance already add a few minutes of overlap).
MERGE_MAX_OVERLAP_S = 30 * 60
_GENERIC_PHONE_NAMES = {"iphone", "ipad", "android", "phone", "tablet", "galaxy", "pixel", "smartphone", "telefono", "cellulare"}

# A device is reported offline only after this number of consecutive failed
# checks (~90s at a 30s interval). Phones in standby and devices with
# WiFi power saving occasionally skip a check: without this
# tolerance their cards changed state (and were replaced) on every cycle.
# The offline detection delay scales with the chosen interval (3 x interval).
MISS_LIMIT = 3

# Fields the probe OBSERVES on the device (not derived from configuration):
# if a check fails but the device is still "tolerated" as online,
# those from the last successful check are kept instead of being cleared.
_OBSERVED = ("mac", "vendor", "vendor_role", "brand", "brand_source", "brand_confidence", "battery", "battery_source", "uptime", "signal_kind", "signal_value", "signal_band", "signal_label", "signal_color")


def _ip_key(device: dict) -> tuple[int, ...]:
    return tuple(int(o) for o in device["ip"].split("."))


class DeviceState:
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
        self._subscribers: set[asyncio.Queue] = set()
        self._wake = asyncio.Event()
        self._force = False  # a manually requested refresh also applies while paused
        self._conflicts_reported: set = set()
        self._paused_until: float | None = self._load_pause()  # epoch; inf = until resumed; None = active
        # Length of the timed pause in seconds (None = stopped until resumed or not paused): the page needs it to
        # draw how far the pause has gone.
        self._paused_total: float | None = self._load_pause_total() if self._paused_until not in (None, float("inf")) else None
        self._task: asyncio.Task | None = None
        self._next_at = 0.0
        self._arp: tuple[float, dict[str, dict]] | None = None
        self._arp_lock = asyncio.Lock()
        self._misses: dict[str, int] = {}
        self._last_seen: dict[str, float] = {}
        self._db_state: dict[str, bool] = {}
        self._bg: set[asyncio.Future] = set()
        # Scans in progress: kept here (and not only in the browser that
        # started them) so that after changing page and coming back the blinking LED and
        # the effect on the search button are found as they were.
        self.rescanning: set[str] = set()
        self._search_running = 0
        self._search_hold_until = 0.0
        self._newdev_macs: frozenset[str] = frozenset()
        self._newdev_lock = asyncio.Lock()
        self._own_ip: str | None = None

    # ---- lifecycle ----
    async def load_history(self) -> None:
        """Restarts from the saved state: without it, after every restart the
        "last seen" of offline devices would be lost."""
        try:
            last = await asyncio.to_thread(history.last_presence)
        except Exception:
            logger.exception("Lettura dello storico presenza fallita")
            return
        for device_id, (online, ts) in last.items():
            self._db_state[device_id] = online
            if not online:
                self._last_seen[device_id] = ts
            mac = await asyncio.to_thread(history.last_mac, device_id)
            if mac:
                self._last_mac[device_id] = mac

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def trigger(self, force: bool = False) -> None:
        """Forces an immediate update cycle (force: even while paused)."""
        if force:
            self._force = True
        self._wake.set()

    # ---- pause of the periodic check ----
    @staticmethod
    def _pause_file():
        return settings.CONFIG_DIR / "pause.json"

    @classmethod
    def _load_pause(cls) -> float | None:
        """The pause survives a service restart (like all settings)."""
        try:
            raw = json.loads(cls._pause_file().read_text(encoding="utf-8")).get("until")
        except (OSError, ValueError, AttributeError):
            return None
        if raw == "forever":
            return float("inf")
        if isinstance(raw, (int, float)) and raw > time.time():
            return float(raw)
        return None

    @classmethod
    def _load_pause_total(cls) -> float | None:
        try:
            raw = json.loads(cls._pause_file().read_text(encoding="utf-8")).get("total")
        except (OSError, ValueError, AttributeError):
            return None
        return float(raw) if isinstance(raw, (int, float)) and raw > 0 else None

    def _save_pause(self) -> None:
        try:
            path = self._pause_file()
            if self._paused_until is None:
                path.unlink(missing_ok=True)
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            until = "forever" if self._paused_until == float("inf") else self._paused_until
            path.write_text(json.dumps({"until": until, "total": self._paused_total}), encoding="utf-8")
        except OSError:
            logger.exception("Pausa non salvata su disco")

    def paused_remaining(self) -> float | None:
        """Seconds until the pause ends (inf = no expiry); None if not paused."""
        if self._paused_until is None:
            return None
        left = self._paused_until - time.time()
        if left <= 0:
            self._paused_until = None
            self._paused_total = None
            return None
        return left

    def pause(self, minutes: int = 0) -> None:
        """Suspends periodic checks for N minutes (0 = until resumed).
        Manually requested actions (refresh, search) remain possible."""
        self._paused_until = time.time() + minutes * 60 if minutes else float("inf")
        self._paused_total = minutes * 60.0 if minutes else None
        self._save_pause()
        logger.info("Controllo periodico in pausa (%s)", f"{minutes} min" if minutes else "fino alla ripresa")
        self._emit(self.poll_info())
        self._wake.set()

    def resume(self) -> None:
        self._paused_until = None
        self._paused_total = None
        self._save_pause()
        logger.info("Controllo periodico ripreso")
        self._force = True
        self._emit(self.poll_info())
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
            "paused_total_ms": int(self._paused_total * 1000)
            if left is not None and left != float("inf") and self._paused_total else None,
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
        q: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_SIZE)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def is_subscribed(self, q: asyncio.Queue) -> bool:
        return q in self._subscribers

    # ---- activities in progress ----
    def track(self, future: asyncio.Future) -> None:
        """Holds a strong reference to a background job: a task without
        references can be garbage collected midway."""
        self._bg.add(future)
        future.add_done_callback(self._bg.discard)

    def activity_info(self) -> dict:
        searching = self._search_running > 0 or time.monotonic() < self._search_hold_until
        return {"type": "activity", "rev": self.rev, "rescanning": sorted(self.rescanning), "search": searching}

    def _emit_activity(self) -> None:
        self._emit(self.activity_info())

    def rescan_started(self, device_ids: list[str]) -> None:
        self.rescanning.update(device_ids)
        self._emit_activity()

    def rescan_finished(self, device_id: str) -> None:
        self.rescanning.discard(device_id)
        self._emit_activity()

    def search_started(self) -> None:
        self._search_running += 1
        self._emit_activity()

    def search_finished(self) -> None:
        self._search_running = max(0, self._search_running - 1)
        # The search is made of two requests (quick, then in-depth): a short
        # hold keeps the effect from switching off and on again between the two.
        self._search_hold_until = time.monotonic() + 2.5
        self._emit_activity()
        asyncio.get_running_loop().call_later(2.6, self._emit_activity)

    def emit_event(self, event: dict) -> None:
        """Generic event to open browsers (e.g. network roles updated)."""
        self._emit(event)

    def emit_alert(self, log_message: str, key: str, **params) -> None:
        """Notice (e.g. new open port): to the log the text as is, to
        open browsers the key and parameters, translated into each one's language."""
        logger.warning(log_message)
        from .storage import journal  # late import: avoids import cycles
        journal.add("normal", key, icon="alert", **params)
        self._emit({"type": "alert", "level": "warning", "key": key, "params": params})

    def _emit(self, event: dict) -> None:
        event = {**event, "rev": self.rev} if "rev" not in event else event
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Client too slow: it is disconnected, it will reconnect by itself
                # and receive the missing differences through catch_up.
                self._subscribers.discard(q)

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
        return await self._arp_by_ip(120)

    async def _arp_by_ip(self, max_age: float) -> dict[str, dict]:
        async with self._arp_lock:
            now = time.monotonic()
            if self._arp is None or now - self._arp[0] > max_age:
                try:
                    hosts = await scanner.arp_scan()
                    self._arp = (time.monotonic(), {h["ip"]: h for h in hosts})
                except Exception:
                    logger.exception("Scansione ARP fallita")
                    if self._arp is None:
                        self._arp = (time.monotonic(), {})
            return self._arp[1]

    def _shadow(self, device_id: str, previous: dict | None, result: dict, now: float) -> None:
        """Data per MAC for later analysis (export/mac_shadow.py). Never decides anything shown, never raises."""
        try:
            job = mac_shadow.observe(device_id, previous, result, self._last_mac.get(device_id), now)
            judge = identity_shift.due(device_id, (result.get("mac") or "").lower(), now)
            if job or judge:
                task = asyncio.create_task(self._shadow_job(device_id, job, result if judge else None, now))
                self._bg.add(task)
                task.add_done_callback(self._bg.discard)
        except Exception:
            logger.debug("mac_shadow failed for %s", device_id, exc_info=True)

    async def _shadow_job(self, device_id: str, job, judge_result: dict | None, now: float) -> None:
        """The memory per MAC is written first (a thread); then, if it is time, the card is judged: two different devices behind it?
        (ha/identity_shift.py). It only reads and notes; a name, brand or type chosen by hand is never touched."""
        try:
            if job:
                await asyncio.to_thread(job)
            if judge_result is not None:
                found = await asyncio.to_thread(identity_shift.evaluate, device_id, judge_result.get("mac"), dict(self._last_mac), now)
                if found and found["new"] and settings.alerts_enabled():
                    name = judge_result.get("name") or judge_result.get("ip")
                    other = identity_shift.describe(found)
                    self.emit_alert("Dietro %s rispondono due dispositivi diversi: %s" % (name, other), "alert.other_device", name=name, other=other)
        except Exception:
            logger.debug("shadow job failed for %s", device_id, exc_info=True)

    def _record_presence(self, result: dict, online: bool, ts: float) -> None:
        """Saves only online/offline transitions to the history."""
        device_id = result["id"]
        if self._db_state.get(device_id) == online:
            return
        self._db_state[device_id] = online
        task = asyncio.create_task(self._write_presence(device_id, result.get("ip"), result.get("mac"), online, ts))
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    async def _write_presence(self, device_id: str, ip: str | None, mac: str | None, online: bool, ts: float) -> None:
        try:
            await asyncio.to_thread(history.record_presence, device_id, ip, mac, online, ts)
        except Exception:
            logger.exception("Salvataggio dello storico presenza fallito per %s", device_id)

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
            devices_config.update_auto_name(device_id, auto[0], auto[1], force=len(auto) > 2 and bool(auto[2]))
        previous = self.devices.get(device_id)
        now = time.time()
        if result.get("mac"):
            if result["online"]:
                self._shadow(device_id, previous, result, now)
            self._last_mac[device_id] = result["mac"]
        if result["online"]:
            latency.tracker.add(device_id, sample)
        if result["online"]:
            self._misses[device_id] = 0
            self._last_seen[device_id] = now
            self._record_presence(result, True, now)
        else:
            misses = self._misses.get(device_id, 0) + 1
            self._misses[device_id] = misses
            if previous is not None and previous["online"] and misses < self._miss_limit():
                result = {
                    **result, "online": True,
                    "extra": {**previous["extra"], **result["extra"]},
                    **{k: previous.get(k) for k in _OBSERVED},
                }
            else:
                # The event carries the instant the device was last seen online, not
                # the moment it was noticed: the chart starts from the real
                # moment of the drop.
                self._record_presence(result, False, self._last_seen.get(device_id, now))
        # Only from offline: for an online device it would change on every cycle and
        # make the card be replaced every 30 seconds for no reason.
        result["last_seen"] = None if result["online"] else self._last_seen.get(device_id)
        # Response time: stepped moving average (changes rarely, so it does not
        # generate an event on every cycle). An offline device has none.
        if result["online"]:
            result["latency_ms"] = latency.tracker.value(device_id)
        else:
            latency.tracker.reset(device_id)
            result["latency_ms"] = None
        result["latency_color"] = latency.color(result["latency_ms"])

        # force: after a search the event is sent anyway, even if the raw data are equal:
        # category and icon are computed at send time (network roles, rules) and the page must redo them.
        if not force and self.devices.get(result["id"]) == result:
            return
        self.devices[result["id"]] = result
        self.rev += 1
        self._rev_of[result["id"]] = self.rev
        self._removed.pop(result["id"], None)
        # The device travels raw: the card and HTML row are rendered by each
        # browser's stream in its own language (see api_events in main.py).
        self._emit({"type": "device", "id": result["id"], "device": result})

    def remove(self, device_id: str) -> None:
        if self.devices.pop(device_id, None) is None:
            return
        self._misses.pop(device_id, None)
        self._last_seen.pop(device_id, None)
        self._db_state.pop(device_id, None)
        latency.tracker.reset(device_id)
        self.rev += 1
        self._rev_of.pop(device_id, None)
        self._removed[device_id] = self.rev
        while len(self._removed) > _MAX_TOMBSTONES:
            self._removed.pop(next(iter(self._removed)))
        self._emit({"type": "removed", "id": device_id})

    async def poll_once(self) -> None:
        snapshot = devices_config.load_devices()
        update_generic_titles(snapshot)
        arp_task = asyncio.create_task(self._arp_by_ip(0))
        # Response time measured in parallel with the probes, in the same cycle.
        lat_task = asyncio.create_task(
            latency.measure_many([(d["id"], d["ip"], d.get("port", 80)) for d in snapshot]))
        results = await asyncio.gather(
            *(probe.probe_device({**d, "last_mac": self._last_mac.get(d["id"])}, arp_task) for d in snapshot),
            return_exceptions=True,
        )
        try:
            samples = await lat_task
        except Exception:
            samples = {}
        current = {c["id"]: c for c in devices_config.load_devices()}
        for config, result in zip(snapshot, results):
            if isinstance(result, Exception):
                logger.error("Probe fallito per %s: %r", config.get("ip"), result)
                continue
            self._apply(config, result, current, samples.get(config["id"]))
        for device_id in [i for i in self.devices if i not in current]:
            self.remove(device_id)
        await self._save_latency()
        try:
            arp = await arp_task  # already completed by the probes: no new scan
        except Exception:
            arp = {}
        await self.follow_ip_changes(arp)
        await self.merge_duplicate_phones()
        self.report_ip_conflicts()
        await self.check_new_devices(arp)
        self.ready.set()

    def report_ip_conflicts(self) -> None:
        """Warns once for each IP answered by different MACs (scanner.arp_conflicts)."""
        for ip, macs in scanner.arp_conflicts.items():
            key = (ip, tuple(macs))
            if key in self._conflicts_reported:
                continue
            self._conflicts_reported.add(key)
            self.emit_alert(f"IP duplicato {ip}: risponde da {', '.join(macs)}", "alert.ip_conflict", ip=ip, macs=", ".join(macs))

    async def follow_ip_changes(self, arp: dict[str, dict]) -> None:
        """An offline device whose (already known) MAC now answers at exactly ONE other
        IP not assigned to other devices has changed address (DHCP): it is followed
        instead of being given up as off. No action if the candidates are ambiguous."""
        if not arp:
            return
        by_mac: dict[str, list[str]] = {}
        for ip, host in arp.items():
            mac = newdevices.normalize_mac(host.get("mac"))
            if mac:
                by_mac.setdefault(mac, []).append(ip)
        configs = devices_config.load_devices()
        used = {c["ip"] for c in configs}
        for config in configs:
            device = self.devices.get(config["id"])
            mac = newdevices.normalize_mac(self._last_mac.get(config["id"]))
            if not device or device.get("online") or not mac or config["ip"] in arp:
                continue
            # A MAC on multiple IPs belongs to a Wi-Fi repeater that "lends" its own
            # address to the clients connected to it (MAC translation): it does not identify a
            # device, so nothing is followed.
            if len(by_mac.get(mac, [])) != 1:
                continue
            candidates = [ip for ip in by_mac[mac] if ip not in used]
            if len(candidates) != 1:
                continue
            new_ip = candidates[0]
            old_ip = await asyncio.to_thread(devices_config.update_ip, config["id"], new_ip)
            if old_ip is None:
                continue
            used.discard(old_ip)
            used.add(new_ip)
            self._misses[config["id"]] = 0
            label = device.get("name") or old_ip
            self.emit_alert(f"{label}: IP cambiato {old_ip} -> {new_ip}", "alert.ip_changed",
                            label=label, old=old_ip, new=new_ip)
            self.trigger()

    @staticmethod
    def _duplicate_key(device: dict) -> str | None:
        """Name that identifies a phone well enough to say that two cards are the same one; None if it does not
        (a bare "iPhone", the IP, a placeholder, a brand)."""
        from .recognition import brands, naming
        name = (device.get("name") or "").strip()
        key = "".join(ch for ch in name.lower() if ch.isalnum())
        if len(key) < 4 or name == device.get("ip") or naming.is_placeholder(name) or key in _GENERIC_PHONE_NAMES:
            return None
        known = brands.known_brand(name)
        if known and "".join(ch for ch in known.lower() if ch.isalnum()) == key:
            return None
        return key

    async def merge_duplicate_phones(self) -> None:
        """A phone that changes IP and private MAC leaves an offline card and gets a new one. When exactly two mobile
        cards have the same distinctive name, at least one is online now and they were never online together for
        long, they are the same device: the older card (it keeps the choices made by hand and the history) takes the
        address of the one that answers, the other disappears and its history goes with it. Nothing is done if it is
        not clear (three cards, same name online together)."""
        groups: dict[str, list[dict]] = {}
        for device in self.devices.values():
            key = self._duplicate_key(device) if device.get("is_mobile") else None
            if key:
                groups.setdefault(key, []).append(device)
        now = time.time()
        outcome = {"merged": 0, "three_or_more": 0, "both_offline": 0, "online_together": 0}
        for cards in groups.values():
            if len(cards) < 2:
                continue
            if len(cards) != 2:
                outcome["three_or_more"] += 1
                continue
            if not any(c.get("online") for c in cards):
                outcome["both_offline"] += 1
                continue
            first_seen = await asyncio.to_thread(history.first_presence, [c["id"] for c in cards])
            older, newer = sorted(cards, key=lambda c: first_seen.get(c["id"], now))
            overlap = await asyncio.to_thread(history.online_overlap, older["id"], newer["id"], now - 7 * 86400, now)
            if overlap > MERGE_MAX_OVERLAP_S:
                outcome["online_together"] += 1
                continue
            await self._merge_cards(keep=older, drop=newer, now=now)
            outcome["merged"] += 1
        # counts only (for the export): they explain a merge that did not happen without any name
        self.merged_total += outcome["merged"]
        self.merge_report = {**outcome, "merged_total": self.merged_total}

    async def _merge_cards(self, keep: dict, drop: dict, now: float) -> None:
        keep_id, drop_id = keep["id"], drop["id"]
        old_ip, new_ip = keep["ip"], drop["ip"]
        # the address that answers is the one kept: the card that is online decides it
        address = new_ip if drop.get("online") or not keep.get("online") else old_ip
        configs = {c["id"]: c for c in devices_config.load_devices()}
        if keep_id not in configs or drop_id not in configs:
            return
        newer_scan = (configs[drop_id].get("scan_info") or {})
        ok = await asyncio.to_thread(devices_config.remove_device, drop_id)
        if not ok:
            return
        if address != old_ip:
            moved = await asyncio.to_thread(devices_config.update_ip, keep_id, address)
            if moved is None:
                return
        if newer_scan.get("scanned_at", 0) > (configs[keep_id].get("scan_info") or {}).get("scanned_at", 0):
            await asyncio.to_thread(devices_config.update_scan_info, keep_id, newer_scan)
        await asyncio.to_thread(history.reassign_device, drop_id, keep_id)
        if self._last_mac.get(drop_id):
            self._last_mac[keep_id] = self._last_mac.pop(drop_id)
        self._misses[keep_id] = 0
        self.remove(drop_id)
        label = keep.get("name") or old_ip
        self.emit_alert(f"{label}: schede unite (stesso telefono) {drop_id} -> {keep_id}", "alert.duplicate_merged",
                        label=label, old=old_ip if address != old_ip else new_ip, new=address)
        self.trigger()

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
        """Stores the list of 'new' devices and emits the event only if the set
        of MACs has changed."""
        macs = frozenset(d["mac"] for d in devices)
        changed = macs != self._newdev_macs
        self._newdev_macs = macs
        if changed:
            self._emit(newdevices.event(devices))

    async def new_devices_event(self) -> dict:
        """Event with the current list (initial frame of api_events)."""
        devices = await asyncio.to_thread(newdevices.list_new)
        return newdevices.event(devices)

    async def check_new_devices(self, arp: dict[str, dict] | None = None) -> None:
        """Compares the seen MACs (ARP already available, no new scan)
        with the known ones; warns about never-seen ones."""
        if arp is None:
            arp = self._arp[1] if self._arp else {}
        async with self._newdev_lock:
            try:
                configs = devices_config.load_devices()
                configured_macs = {m for m in (newdevices.normalize_mac(d.get("mac")) for d in self.devices.values()) if m}
                skip_ips = {self._own_ip} if self._own_ip else set()
                if self._own_ip is None:
                    try:
                        _, self._own_ip = await netutil.get_local_network()
                        skip_ips = {self._own_ip}
                    except Exception:
                        pass
                observed = newdevices.observed_macs(arp, dhcp.seen, skip_ips)
                observed = {m: o for m, o in observed.items()
                            if not blocklist.matches(mac=m, ip=o["ip"], name=o["hostname"])}
                fresh, current = await asyncio.to_thread(
                    newdevices.evaluate, observed, {c["ip"] for c in configs}, configured_macs, newdevices.own_macs(),
                )
            except Exception:
                logger.exception("Controllo nuovi dispositivi fallito")
                return
            alerts_on = settings.alerts_enabled()
            for dev in fresh:
                label = newdevices.readable_label(dev)
                ip = dev["ip"] or "-"
                message = f"Nuovo dispositivo in rete: {label} ({ip}) MAC {dev['mac']}"
                if alerts_on:
                    self.emit_alert(message, "alert.new_device", label=label, ip=ip)
                else:
                    logger.info(message)
            self.set_new_devices(current)

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
            probe.probe_device({**config, "last_mac": self._last_mac.get(device_id)}, arp_task),
            latency.measure(config["ip"], config.get("port", 80)),
        )
        current = {c["id"]: c for c in devices_config.load_devices()}
        self._apply(config, result, current, sample, force=force)

    async def _loop(self) -> None:
        while True:
            # clear at the start: a trigger that arrives during the cycle starts
            # the next one immediately instead of being lost.
            self._wake.clear()
            if self.paused_remaining() is None or self._force:
                self._force = False
                try:
                    await self.poll_once()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Ciclo di aggiornamento fallito")
                    self.ready.set()
            else:
                self.ready.set()
            # Re-read on every cycle: a change from Settings applies immediately
            # (the API wakes the cycle with trigger()).
            interval = self._interval()
            left = self.paused_remaining()
            # While paused, restart as soon as it ends, not one interval later.
            wait = interval if left is None else min(interval, left + 0.2)
            self._next_at = time.monotonic() + wait
            self._emit(self.poll_info())
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=wait)
            except asyncio.TimeoutError:
                pass


state = DeviceState()
