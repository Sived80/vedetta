"""The state of every card for the page (ha/analysis_view.py): what is collected from the evidence card, how the rule of analysis/status.py is applied with its memory (a card under analysis must climb past 60 to leave it), the
snapshot (only the cards that are not identified, with the badge of their corner), and the event: one when something changed, none when nothing did, and none of it sends anything to a device (the functions that read are
handed in, here they are fakes)."""
import asyncio
import os
import sys
import tempfile
import time

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.analysis import status as st  # noqa: E402
from app.ha import analysis_view as av  # noqa: E402

NOW = 1_000_000.0
DAY = 86400.0


def group(certainty, value="router", rival=False, basis="auto"):
    return {"value": value, "certainty": certainty, "basis": basis, "rejected": [{"group": "phone", "points": 3}] if rival else [], "clues": []}


# --- collect: the group part, the points, the group shown and the age; a card that cannot be read is left out; a card with no presence event counts as old
CARDS = {"a": group(90), "b": group(30, rival=True), "c": group(30, rival=True), "d": None}


def debug_of(card_id):
    if CARDS[card_id] is None:
        raise RuntimeError("unreadable")
    return {"type": {"scores": {"router": 12, "phone": 3}}, "id": card_id}


def summarize(debug, device):
    return {"group": CARDS[debug["id"]]}


got = av.collect(["a", "b", "c", "d"], NOW, debug_of=debug_of, summarize=summarize, devices={k: {} for k in CARDS}, first_seen=lambda ids: {"a": NOW - 3 * DAY, "b": NOW - 600})
assert sorted(got) == ["a", "b", "c"], "a card that raises is left out, the others stay: %s" % sorted(got)
assert got["a"]["age_s"] == 3 * DAY and got["b"]["age_s"] == 600 and got["c"]["age_s"] == av.OLD_S, got
assert got["a"]["scores"] == {"router": 12, "phone": 3} and got["a"]["chosen"] == "router" and got["a"]["group"]["certainty"] == 90

# --- assess_all: identified, settling (a young card with low certainty and a rival), analysing (an old one)
states = av.assess_all(got, {})
assert (states["a"].state, states["b"].state, states["c"].state) == (st.IDENTIFIED, st.SETTLING, st.ANALYSING), {k: v.state for k, v in states.items()}

# the memory: under analysis, 55 is not enough to leave (the high threshold is 60); a card that was not under analysis stays identified at 55
inputs = {"x": {"group": group(55, rival=True), "scores": {}, "chosen": "router", "age_s": av.OLD_S}, "y": {"group": group(55, rival=True), "scores": {}, "chosen": "router", "age_s": av.OLD_S}}
prev = {"x": st.Status(st.ANALYSING, []), "y": st.Status(st.IDENTIFIED, [])}
out = av.assess_all(inputs, prev)
assert out["x"].state == st.ANALYSING and out["y"].state == st.IDENTIFIED, {k: v.state for k, v in out.items()}
inputs["x"]["group"] = group(61, rival=True)
assert av.assess_all(inputs, prev)["x"].state == st.IDENTIFIED, "above 60 it leaves"

# --- snapshot: only what is not identified, with the badge of its corner (a lens at the top right, an hourglass at the bottom right)
snap = av.snapshot(states)
assert sorted(snap) == ["b", "c"], snap
assert snap["c"] == {"state": "analysing", "reasons": ["low_certainty"], "badges": [{"id": "analysing", "corner": "top_right"}]}, snap["c"]
assert snap["b"]["state"] == "settling" and snap["b"]["badges"] == [{"id": "settling", "corner": "bottom_right"}], snap["b"]

# --- refresh: an event when something changed, none when nothing did; a card that goes away leaves the results
EVENTS = []
av._on_change = EVENTS.append
av.state.devices.clear()
av.state.devices.update({"a": {}, "c": {}})
av.RESULTS.clear()


def fake_collect(ids, now, **kw):
    return {k: v for k, v in got.items() if k in ids}


av.collect = fake_collect
assert asyncio.run(av.refresh()) is True and len(EVENTS) == 1 and EVENTS[0]["type"] == "analysis" and list(EVENTS[0]["cards"]) == ["c"], EVENTS
assert asyncio.run(av.refresh()) is False and len(EVENTS) == 1, "nothing changed: no event"
av.state.devices.pop("c")
assert asyncio.run(av.refresh()) is True and EVENTS[-1] == {"type": "analysis", "cards": {}} and "c" not in av.RESULTS, EVENTS[-1]
assert av.event() == {"type": "analysis", "cards": {}}

# --- start and stop: the loop is created once and released
async def loop_cycle():
    av.start()
    first = av._task
    av.start()
    assert av._task is first, "started twice: still one task"
    await av.stop()
    assert av._task is None and first.cancelled()


asyncio.run(loop_cycle())
# --- the clock of the analysis and the expiry (the state of a card that stays under analysis for a week is «unresolved»)
WEEK = st.MAX_ANALYSIS_S
stuck = {"x": {"group": group(20, value="generic"), "scores": {}, "chosen": "generic", "age_s": av.OLD_S}}
clock = {}
r = av.assess_all(stuck, {}, clock, 1000.0)
assert r["x"].state == st.ANALYSING and clock == {"x": 1000.0}, "entering analysis starts the clock"
r = av.assess_all(stuck, r, clock, 1000.0 + WEEK - 1)
assert r["x"].state == st.ANALYSING and clock == {"x": 1000.0}, "the clock is not restarted"
r = av.assess_all(stuck, r, clock, 1000.0 + WEEK)
assert r["x"].state == st.UNRESOLVED and r["x"].reasons[-1] == "expired", r["x"]
assert av.snapshot(r)["x"]["badges"] == [{"id": "unresolved", "corner": "top_right"}] and av.snapshot(r)["x"]["state"] == "unresolved"
r = av.assess_all(stuck, r, clock, 1000.0 + 2 * WEEK)
assert r["x"].state == st.UNRESOLVED and clock == {"x": 1000.0}, "it stays unresolved while the evidence stays as poor"
better = {"x": dict(stuck["x"], group=group(80, value="router"))}
r = av.assess_all(better, r, clock, 1000.0 + 2 * WEEK + 5)
assert r["x"].state == st.IDENTIFIED and clock == {}, "the evidence improved: identified, and the clock is gone"
r = av.assess_all(stuck, r, clock, 1000.0 + 3 * WEEK)
assert r["x"].state == st.ANALYSING and clock == {"x": 1000.0 + 3 * WEEK}, "falling back starts a new clock, not the old week"

# the clocks are kept on disk (a restart must not give a card a new week), a card that is gone loses its clock, a broken file starts them again with a word in the log
import json  # noqa: E402
import logging  # noqa: E402
from pathlib import Path  # noqa: E402
av.SINCE_PATH = Path(tempfile.mkdtemp()) / "analysis_since.json"
av._since.clear()
av._since.update({"keep": 5.0, "gone": 6.0})
av.state.devices.clear()
av.state.devices.update({"keep": {}})
av.RESULTS.clear()
av.collect = lambda ids, now, **kw: {}
asyncio.run(av.refresh())
assert json.loads(av.SINCE_PATH.read_text(encoding="utf-8")) == {"keep": 5.0}, "the clock of a card that is gone was dropped and the rest saved"
av._since.clear()
av._load_since()
assert av._since == {"keep": 5.0}, "loaded again after a restart"
records = []


class Catch(logging.Handler):
    def emit(self, record):
        records.append(record)


av.logger.addHandler(Catch())
av.SINCE_PATH.write_text("{broken", encoding="utf-8")
av._since.clear()
av._load_since()
assert av._since == {} and [r.levelno for r in records] == [logging.WARNING], [r.getMessage() for r in records]
av.SINCE_PATH.write_text("[1, 2]", encoding="utf-8")
av._load_since()
assert av._since == {}, "a file that is not an object is ignored"
av.SINCE_PATH = Path(tempfile.mkdtemp()) / "missing.json"
av._load_since()
assert av._since == {} and len(records) == 1, "no file is the normal start: no word in the log"

# --- the first judgement waits for the evidence to settle: a card judged at the start (no roles yet, low certainty) would get stuck under analysis by the hysteresis
SLEPT = []


class Stop(Exception):
    pass


async def fake_sleep(seconds):
    SLEPT.append(seconds)
    raise Stop


real_sleep = av.asyncio.sleep
av.asyncio.sleep = fake_sleep
try:
    asyncio.run(av._loop())
except Stop:
    pass
finally:
    av.asyncio.sleep = real_sleep
assert SLEPT == [av.FIRST_AFTER_S] and av.FIRST_AFTER_S >= 300, SLEPT
print("TUTTO OK")
