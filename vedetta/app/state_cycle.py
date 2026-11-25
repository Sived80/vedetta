"""The periodic check of DeviceState and its decisions: one cycle (probes, response times and the network table together, the results applied, what is gone forgotten, the housekeeping that follows),
the loop that repeats it, and the online/offline decision of a checked device (settle, publish).

Presence by MAC (1.0 step P5): every probe is told the card's usable link and those of the other cards (probe_inputs, linkview); after the probes
a linked card left offline whose MAC answered alone at another address in THIS cycle is online there (macpresence.elsewhere), and the move is
planned for the end of the cycle. A silent phone that a router tracker of Home Assistant says is at home stays online (ha/tracker_hold, 1.0.3)."""
import asyncio
import time

from . import identity_changes, linkview, macpresence, macverdict, netutil, sentinel_view
from .applog import logger
from .ha import tracker_hold
from .storage.history import history
from .formatters import update_generic_titles
from .scan import latency, presence_confirm, probe, touch_policy
from .networks import registry
from .storage import devices_config


def latency_targets(snapshot: list[dict]) -> list[tuple]:
    """(id, ip, port) of the devices whose response time is measured: not those that must not be touched."""
    return [(d["id"], d["ip"], d.get("port", 80)) for d in snapshot if touch_policy.may_touch(d)]


def probe_inputs(state, configs: list[dict]) -> list[dict]:
    """What each probe is told: the card, its usable link (`link`, None without one: linkview), the MAC its names are asked with (`last_mac`:
    the link, else the last MAC seen) and the usable links of the other cards (`links_of_others`, lower case)."""
    return _inputs(state, configs, _link_checks(configs, time.time()))


def _inputs(state, configs: list[dict], checks: dict[str, tuple]) -> list[dict]:
    links = {i: m for i, (m, _) in checks.items() if m}
    every = {m.lower() for m in links.values()}
    return [{**d, "last_mac": links.get(d["id"]) or state._last_mac.get(d["id"]), "link": links.get(d["id"]),
             "links_of_others": frozenset(every - {(links.get(d["id"]) or "").lower()})} for d in configs]


def probe_input(state, config: dict, configs: list[dict]) -> dict:
    """What the probe of one card is told (the refresh of a single card), the same as in a cycle."""
    return next(i for i in probe_inputs(state, configs) if i["id"] == config["id"])


async def probe_one(state, config: dict, configs: list[dict], arp_task) -> dict:
    """The probe of one card (the refresh of a single card), with the same hold by Home Assistant as in a cycle (ha/tracker_hold)."""
    told = probe_input(state, config, configs)
    result = await probe.probe_device(told, arp_task)
    await tracker_hold.mark([told], [result])
    return result


def _link_checks(configs: list[dict], now: float) -> dict[str, tuple]:
    """Card id -> (the MAC of its link or None, why: linkview.REASONS or "used"), for the cards that have a stored link; the network of each card
    worked out as the judgement does."""
    linked = [d for d in configs if linkview.row(d["id"])]
    if not linked:
        return {}
    nets = registry.direct_networks([d["ip"] for d in linked if d.get("ip")], netutil.last_network)
    return {d["id"]: linkview.check(d["id"], d.get("seq"), nets.get(d.get("ip")), now) for d in linked}


def _note_links(checks: dict[str, tuple]) -> None:
    """The counts of the export: one cycle, its links used and not used (by reason)."""
    linkview.note("cycles")
    for _, why in checks.values():
        linkview.note("used") if why == "used" else linkview.note("unused", reason=why)


async def poll_once(state) -> None:
    snapshot = devices_config.load_devices()
    registry.propose([d["ip"] for d in snapshot])
    snapshot = registry.mark_off_limits(snapshot)
    update_generic_titles(snapshot)
    started = time.time()
    arp_task = asyncio.create_task(state._arp_by_ip(0))
    # Response time measured in parallel with the probes, in the same cycle.
    lat_task = asyncio.create_task(latency.measure_many(latency_targets(snapshot)))
    checks = _link_checks(snapshot, time.time())
    _note_links(checks)
    inputs = _inputs(state, snapshot, checks)
    results = await asyncio.gather(*(probe.probe_device(i, arp_task) for i in inputs), return_exceptions=True)
    samples = await _samples(lat_task)
    moves = await _found_elsewhere(state, inputs, results, arp_task, started)
    await presence_confirm.confirm_before_offline(state, inputs, results)
    await tracker_hold.mark(inputs, results)
    _apply_results(state, snapshot, results, samples)
    await state._save_latency()
    await _after_cycle(state, await _arp_of(arp_task), moves)
    state.ready.set()


async def _found_elsewhere(state, inputs: list[dict], results: list, arp_task, started: float) -> dict[str, str]:
    """The linked cards the probes left offline whose MAC answered alone at one other address in this cycle: online there, by their MAC (the
    result is changed in place), and the move planned (card id -> address). Nothing is asked of the network: the view of this cycle is read."""
    waiting = [k for k, (i, r) in enumerate(zip(inputs, results)) if i["link"] and isinstance(r, dict) and not r.get("online")]
    if not waiting:
        return {}
    view = await _arp_of(arp_task)
    answers = state._view.answered_since(started)
    moves = {}
    for k in waiting:
        if macpresence.at_address(inputs[k]["link"], view.get(inputs[k]["ip"]), macverdict.shared) == "other":
            linkview.note("other_at_address")
        where = macpresence.elsewhere(inputs[k]["link"], answers)
        if where is not None:
            results[k] = {**results[k], "online": True, "mac": inputs[k]["link"]}
            moves[inputs[k]["id"]] = where
            linkview.note("found_elsewhere")
    return moves


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


async def _after_cycle(state, arp: dict, moves: dict[str, str]) -> None:
    """What follows a cycle: the linked cards found at another address follow their MAC (`moves`), duplicate phones, conflicts, new devices and the
    MAC layer."""
    await state.follow_links(moves)
    await state.merge_duplicate_phones()
    state.report_ip_conflicts()
    await state.name_twins()
    await state.check_new_devices(arp)
    await state._record_macs(arp)


STALL_FLOOR_S = 300        # the loop counts as stalled only after max(STALL_FLOOR_S, STALL_INTERVALS x interval) without a turn
STALL_INTERVALS = 5


async def loop(state, min_gap: float) -> None:
    while True:
        state._alive_at = time.monotonic()      # one turn of the loop: a cycle done, or a pause waited out (stalled() reads it)
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
    polled = await _poll(state)
    state._note_end(state._last_start)
    if polled:
        sentinel_view.after_cycle(state.devices, state.emit_alert)      # what is ready goes out, once per cycle


async def _poll(state) -> bool:
    """One check of the devices. True once a check has succeeded since the start: before that the cards are still empty (after a restart),
    and the Sentinel's end of cycle would take every card as deleted and close the "down" events already sent, whose "back" would then never go out."""
    try:
        await state.poll_once()
        state._polled_ok = True
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Ciclo di aggiornamento fallito")
        state.ready.set()
    return state._polled_ok


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
    elif result.get("presence_held"):
        result = _held(state, device_id, result, previous, now)
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


def _held(state, device_id: str, result: dict, previous: dict | None, now: float) -> dict:
    """A silent phone that Home Assistant's router says is at home (ha/tracker_hold): online and present in the history, with the data it
    observed when it last answered; no response time is added (it gave none)."""
    state._misses[device_id] = 0
    state._last_seen[device_id] = now
    state._record_presence(result, True, now)
    seen = previous if previous and previous.get("online") else {}
    return {**result, "online": True, "extra": {**seen.get("extra", {}), **result.get("extra", {})}, **{k: seen[k] for k in OBSERVED if k in seen}}


def _fill_latency(device_id: str, result: dict) -> None:
    """Response time: stepped moving average (changes rarely, so it does not generate an event on every cycle). An offline device has none."""
    if result["online"]:
        result["latency_ms"] = latency.tracker.value(device_id)
    else:
        latency.tracker.reset(device_id)
        result["latency_ms"] = None
    result["latency_color"] = latency.color(result["latency_ms"])


_identity_tasks: set = set()


def _remember_identity(rows: list[dict]) -> None:
    """The changes of name and brand go to the history in the background (one small transaction), never in the way of the cycle."""
    if not rows:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:            # no loop (a test that drives the state by hand): nothing to remember, never an error for the cycle
        return
    task = loop.create_task(asyncio.to_thread(_write_identity, rows))
    _identity_tasks.add(task)
    task.add_done_callback(_identity_tasks.discard)


def _write_identity(rows: list[dict]) -> None:
    try:
        history.identity_record(rows)
    except Exception:
        logger.exception("Storia del riconoscimento non salvata")


def publish(state, result: dict, force: bool) -> None:
    """Stores the result and sends the event, unless nothing changed. force: after a search the event is sent anyway, even if the raw data are equal: category and icon are computed at
    send time (network roles, rules) and the page must redo them."""
    before = state.devices.get(result["id"])
    if not force and before == result:
        return
    _remember_identity(identity_changes.between(before, result, time.time()))
    state.devices[result["id"]] = result
    state.rev += 1
    state._rev_of[result["id"]] = state.rev
    state._removed.pop(result["id"], None)
    # The device travels raw: the card and HTML row are rendered by each browser's stream in its own language (see api_events in main.py).
    state.emit_event({"type": "device", "id": result["id"], "device": result})


def stalled(alive_at: float | None, now: float, interval: float) -> tuple[bool, float | None]:
    """Pure: is the loop of the checks stuck? (stuck, seconds since its last turn). A turn of the loop comes at least every interval,
    a pause included (it waits at most one interval); a cycle that never ends (a probe that hangs) stops the turns. Before the
    first turn nothing is judged: the start-up has its own grace in run.sh."""
    if alive_at is None:
        return False, None
    age = now - alive_at
    return age > max(STALL_FLOOR_S, STALL_INTERVALS * interval), age

