"""The periodic check of DeviceState and its decisions: one cycle (probes, response times and the network table together, the results applied, what is gone forgotten, the housekeeping that follows),
the loop that repeats it, and the online/offline decision of a checked device (settle, publish)."""
import asyncio
import time

from .applog import logger
from .formatters import update_generic_titles
from .scan import latency, presence, probe, touch_policy
from .storage import devices_config


def latency_targets(snapshot: list[dict]) -> list[tuple]:
    """(id, ip, port) of the devices whose response time is measured: not those that must not be touched."""
    return [(d["id"], d["ip"], d.get("port", 80)) for d in snapshot if touch_policy.may_touch(d)]


async def poll_once(state) -> None:
    snapshot = devices_config.load_devices()
    update_generic_titles(snapshot)
    arp_task = asyncio.create_task(state._arp_by_ip(0))
    # Response time measured in parallel with the probes, in the same cycle.
    lat_task = asyncio.create_task(latency.measure_many(latency_targets(snapshot)))
    owner = presence.owners(state._last_mac)
    results = await asyncio.gather(
        *(probe.probe_device({**d, "last_mac": state._last_mac.get(d["id"]), "mac_owner": owner}, arp_task) for d in snapshot),
        return_exceptions=True,
    )
    samples = await _samples(lat_task)
    _apply_results(state, snapshot, results, samples)
    await state._save_latency()
    await _after_cycle(state, await _arp_of(arp_task))
    state.ready.set()


async def _samples(lat_task) -> dict:
    """Response times measured in parallel with the probes, in the same cycle (none if the measurement failed)."""
    try:
        return await lat_task
    except Exception:
        return {}


async def _arp_of(arp_task) -> dict:
    """The network table, already completed by the probes: no new scan."""
    try:
        return await arp_task
    except Exception:
        return {}


def _apply_results(state, snapshot: list[dict], results: list, samples: dict) -> None:
    """Applies every probe result; a configuration that changed meanwhile makes the result stale (see _apply); the devices that are gone are forgotten."""
    current = {c["id"]: c for c in devices_config.load_devices()}
    for config, result in zip(snapshot, results):
        if isinstance(result, Exception):
            logger.error("Probe fallito per %s: %r", config.get("ip"), result)
            continue
        state._apply(config, result, current, samples.get(config["id"]))
    for device_id in [i for i in state.devices if i not in current]:
        state.remove(device_id)


async def _after_cycle(state, arp: dict) -> None:
    """What follows a cycle: changed addresses, duplicate phones, conflicts, new devices and the MAC layer."""
    await state.follow_ip_changes(arp)
    await state.merge_duplicate_phones()
    state.report_ip_conflicts()
    await state.check_new_devices(arp)
    await state._record_macs(arp)


async def loop(state, min_gap: float) -> None:
    while True:
        # clear at the start: a trigger that arrives during the cycle starts the next one immediately instead of being lost.
        state._wake.clear()
        if state.paused_remaining() is None or state._force:
            await _run_cycle(state, min_gap)
        else:
            state.ready.set()
        await _sleep_until_wake(state)


async def _run_cycle(state, min_gap: float) -> None:
    forced = state._force
    state._force = False
    await _wait_gap(state, forced, min_gap)
    state._last_start = time.monotonic()
    state._note_start(state._cause or ("force" if forced else ""))
    try:
        await state.poll_once()
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Ciclo di aggiornamento fallito")
        state.ready.set()
    state._note_end(state._last_start)


async def _wait_gap(state, forced: bool, min_gap: float) -> None:
    """A cycle woken by an event, not by the timer, never starts closer than min_gap seconds to the last one (a refresh asked by the user is never delayed)."""
    if state._cause and not forced:
        gap = min_gap - (time.monotonic() - state._last_start)
        if gap > 0:
            await asyncio.sleep(gap)


async def _sleep_until_wake(state) -> None:
    """Waits for the interval (re-read on every cycle: a change from Settings applies immediately, the API wakes the cycle with trigger()) or for a wake-up."""
    interval = state._interval()
    left = state.paused_remaining()
    # While paused, restart as soon as it ends, not one interval later.
    wait = interval if left is None else min(interval, left + 0.2)
    state._next_at = time.monotonic() + wait
    state.emit_event(state.poll_info())
    try:
        await asyncio.wait_for(state._wake.wait(), timeout=wait)
        state._cause = state._wake_reason or "other"
    except asyncio.TimeoutError:
        state._cause = ""
    state._wake_reason = ""


# --- The decision of DeviceState._apply about a checked device, in small steps: online or offline (with the tolerance to missed checks), last seen, response time, and the storing of the (was py)

# Fields the probe OBSERVES on the device (not derived from configuration):
# if a check fails but the device is still "tolerated" as online,
# those from the last successful check are kept instead of being cleared.
OBSERVED = ("mac", "vendor", "vendor_role", "brand", "brand_source", "brand_confidence", "battery", "battery_source", "uptime", "signal_kind", "signal_value", "signal_band", "signal_label", "signal_color")


def settle(state, device_id: str, result: dict, previous: dict | None, now: float, sample: float | None) -> dict:
    """Online or offline, last seen and response time of a checked device; returns the result to keep."""
    if result["online"]:
        latency.tracker.add(device_id, sample)
        state._misses[device_id] = 0
        state._last_seen[device_id] = now
        state._record_presence(result, True, now)
    else:
        result = _after_miss(state, device_id, result, previous, now)
    # Only from offline: for an online device it would change on every cycle and make the card be replaced every 30 seconds for no reason.
    result["last_seen"] = None if result["online"] else state._last_seen.get(device_id)
    _fill_latency(device_id, result)
    return result


def _after_miss(state, device_id: str, result: dict, previous: dict | None, now: float) -> dict:
    """The device did not answer: it stays online (with the data observed before) until the limit of misses is passed."""
    misses = state._misses.get(device_id, 0) + 1
    state._misses[device_id] = misses
    if previous is not None and previous["online"] and misses < state._miss_limit():
        return {**result, "online": True, "extra": {**previous["extra"], **result["extra"]}, **{k: previous.get(k) for k in OBSERVED}}
    # The event carries the instant the device was last seen online, not the moment it was noticed: the chart starts from the real moment of the drop.
    state._record_presence(result, False, state._last_seen.get(device_id, now))
    return result


def _fill_latency(device_id: str, result: dict) -> None:
    """Response time: stepped moving average (changes rarely, so it does not generate an event on every cycle). An offline device has none."""
    if result["online"]:
        result["latency_ms"] = latency.tracker.value(device_id)
    else:
        latency.tracker.reset(device_id)
        result["latency_ms"] = None
    result["latency_color"] = latency.color(result["latency_ms"])


def publish(state, result: dict, force: bool) -> None:
    """Stores the result and sends the event, unless nothing changed. force: after a search the event is sent anyway, even if the raw data are equal: category and icon are computed at
    send time (network roles, rules) and the page must redo them."""
    if not force and state.devices.get(result["id"]) == result:
        return
    state.devices[result["id"]] = result
    state.rev += 1
    state._rev_of[result["id"]] = state.rev
    state._removed.pop(result["id"], None)
    # The device travels raw: the card and HTML row are rendered by each browser's stream in its own language (see api_events in main.py).
    state.emit_event({"type": "device", "id": result["id"], "device": result})
