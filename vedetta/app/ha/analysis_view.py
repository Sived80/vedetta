"""The state of every card (identified, settling, analysing) for the page.

It is computed now and then from the evidence card that the app already builds for each device (ha/device_debug.py, recognition/evidence.py) with the rule of analysis/status.py, and it is sent to the page as a snapshot (/api/ha/devices) and as
an event ("analysis"). Read-only: it sends nothing to any device and changes no type, brand or name. Only the cards that are NOT identified are told: a card that is missing from the snapshot is identified."""
import asyncio
import contextlib
import json
import time

from .. import paths
from ..analysis import badges, status as st
from ..applog import logger
from ..atomic import write_atomic
from ..recognition import evidence
from ..state import state
from ..storage.history import history
from .device_debug import device_debug

REFRESH_S = 120          # the states are judged again this often
FIRST_AFTER_S = 600      # the first time, when the evidence has settled: right after a start the network roles (10 points of a gateway) are not there yet, the certainty is low for a few minutes and a card would enter analysis and
                         # stay there, because to leave it must climb past the high threshold (seen on the export of 12 October: the gateway, certainty 54, under analysis since the start)
OLD_S = 10 ** 9          # a card with no presence event in the history counts as old: nothing says it just appeared

RESULTS: dict[str, st.Status] = {}      # card id -> the last state
SINCE_PATH = paths.data_path("analysis_since.json")
_since: dict[str, float] = {}            # card id -> when it entered analysis, without a break (kept on disk: a restart must not give a card a new week)
_task: asyncio.Task | None = None
_on_change = None


def collect(ids, now: float, *, debug_of=device_debug, summarize=evidence.summarize, devices=None, first_seen=None) -> dict[str, dict]:
    """What the rule needs, for every card: the group part of the evidence card, the points per group, the group shown and the age. A card that cannot be read is left out (and told in the debug log)."""
    devices = state.devices if devices is None else devices
    first = (first_seen or history.first_presence)(list(ids))
    out = {}
    for card_id in ids:
        try:
            debug = debug_of(card_id)
            card = summarize(debug, devices[card_id])
            group = card.get("group") or {}
            out[card_id] = {"group": group, "scores": (debug.get("type") or {}).get("scores") or {}, "chosen": group.get("value"),
                            "age_s": now - first[card_id] if card_id in first else OLD_S}
        except Exception:
            logger.debug("Analysis state not computed for %s", card_id, exc_info=True)
    return out


def assess_all(inputs: dict[str, dict], previous: dict[str, st.Status], since: dict[str, float] | None = None, now: float | None = None) -> dict[str, st.Status]:
    """The state of each card; a card that was under analysis must climb past the high threshold to leave it (previous). `since` holds when each card entered analysis (changed in place): a card
    that is still under analysis after st.MAX_ANALYSIS_S becomes «unresolved»; a card that leaves analysis loses its clock."""
    since = {} if since is None else since
    now = time.time() if now is None else now
    out = {}
    for card_id, i in inputs.items():
        prev = previous[card_id].state if card_id in previous else None
        result = st.assess(i["group"], age_s=i["age_s"], previous=prev, scores=i["scores"], chosen=i["chosen"])
        if result.state == st.ANALYSING:
            result = st.assess(i["group"], age_s=i["age_s"], previous=prev, scores=i["scores"], chosen=i["chosen"], analysing_for_s=now - since.setdefault(card_id, now))
        else:
            since.pop(card_id, None)
        out[card_id] = result
    return out


def _flags(status: st.Status) -> dict:
    return {"analysing": status.state == st.ANALYSING, "settling": status.state == st.SETTLING, "unresolved": status.state == st.UNRESOLVED}


def snapshot(results: dict[str, st.Status] | None = None) -> dict[str, dict]:
    """card id -> {state, reasons, badges} for the cards that are not identified (the page takes a missing card as identified)."""
    results = RESULTS if results is None else results
    return {card_id: {"state": s.state, "reasons": list(s.reasons), "badges": [{"id": b.id, "corner": b.corner} for b in badges.choose(_flags(s))]}
            for card_id, s in results.items() if s.state != st.IDENTIFIED}


def event() -> dict:
    return {"type": "analysis", "cards": snapshot()}


async def refresh() -> bool:
    """Judges every card again; True (and one event to the page) if anything changed."""
    now = time.time()
    inputs = await asyncio.to_thread(collect, list(state.devices), now)
    before = dict(_since)
    new = assess_all(inputs, RESULTS, _since, now)
    for card_id in [c for c in _since if c not in state.devices]:       # a card that is gone loses its clock (one that could only not be read keeps it)
        del _since[card_id]
    if _since != before:
        await asyncio.to_thread(_save_since)
    changed = snapshot(new) != snapshot()
    RESULTS.clear()
    RESULTS.update(new)
    if changed and _on_change:
        _on_change(event())
    return changed


def _save_since() -> None:
    try:
        write_atomic(SINCE_PATH, lambda f: json.dump(_since, f), ".analysis-")
    except OSError:
        logger.warning("Analysis clocks not saved: a restart will start them again", exc_info=True)


def _load_since() -> None:
    try:
        raw = json.loads(SINCE_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return
    except (OSError, ValueError) as exc:
        logger.warning("Analysis clocks not read (%s): they start again", exc.__class__.__name__)
        return
    if isinstance(raw, dict):
        _since.clear()
        _since.update({str(k): float(v) for k, v in raw.items() if isinstance(v, (int, float))})


async def _loop() -> None:
    await asyncio.sleep(FIRST_AFTER_S)
    while True:
        try:
            await refresh()
        except Exception:
            logger.exception("Computing the analysis states failed")
        await asyncio.sleep(REFRESH_S)


def start(on_change=None) -> None:
    global _task, _on_change
    _on_change = on_change
    _load_since()
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())


async def stop() -> None:
    global _task
    if _task:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _task
        _task = None
