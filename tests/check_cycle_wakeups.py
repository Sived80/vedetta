"""Wake-ups of the check cycle. Only the loop of the state starts a cycle, so two cycles can never overlap by construction; what can go wrong is how the wake-ups that arrive WHILE a cycle runs
(a changed address, merged cards, MQTT, the user pressing refresh) are handled. Proved here with a real DeviceState and a slow fake cycle:
  - cycles never overlap, however many wake-ups come;
  - twenty wake-ups during one cycle give exactly ONE more cycle (they are not queued twenty times, and none is lost: the next cycle does happen);
  - a cycle woken by an event never starts closer than min_gap to the last one;
  - a refresh asked by the user is never delayed by the gap."""
import asyncio
import os
import sys
import tempfile
import time

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()      # never the real folder of the developer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import state as state_mod, state_cycle  # noqa: E402

real_sleep = asyncio.sleep
GAP = 0.4
CYCLE = 0.15


def build():
    st = state_mod.DeviceState()
    st.running, st.most, st.starts = 0, 0, []

    async def poll():
        st.running += 1
        st.most = max(st.most, st.running)
        st.starts.append(time.monotonic())
        await real_sleep(CYCLE)
        st.running -= 1
    st.poll_once = poll
    st._interval = staticmethod(lambda: 3600)       # only wake-ups start cycles after the first
    return st


async def run_loop(st):
    return asyncio.create_task(state_cycle.loop(st, GAP))


async def stop(task):
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def case_burst_gives_one_more_cycle():
    st = build()
    task = await run_loop(st)
    await real_sleep(0.05)                            # the first cycle is running
    assert st.running == 1
    for _ in range(20):                               # twenty events during the cycle
        st.trigger(reason="event")
        await real_sleep(0)                           # no timed sleep: on Windows a sleep of 2 ms lasts about 15 ms, and twenty of them outlast the cycle
    await real_sleep(CYCLE + GAP + 0.4)               # the cycle ends, the gap passes, the next one runs
    assert len(st.starts) == 2, "twenty wake-ups during a cycle must give exactly one more cycle, got %d" % len(st.starts)
    assert st.most == 1, "two cycles overlapped"
    assert st.starts[1] - st.starts[0] >= GAP - 0.02, "the cycle woken by an event started closer than the gap: %.2f s" % (st.starts[1] - st.starts[0])
    await stop(task)


async def case_no_event_no_cycle():
    st = build()
    task = await run_loop(st)
    await real_sleep(CYCLE + 0.5)
    assert len(st.starts) == 1, "with nothing to wake it the loop must wait for its interval"
    await stop(task)


async def case_refresh_is_not_delayed():
    st = build()
    task = await run_loop(st)
    await real_sleep(CYCLE + 0.1)                     # the first cycle is over
    asked = time.monotonic()
    st.trigger(force=True, reason="user")
    await real_sleep(0.1)
    assert len(st.starts) == 2 and st.starts[1] - asked < 0.1, "a refresh asked by the user must start at once, not wait for the gap"
    await stop(task)


async def main():
    await case_burst_gives_one_more_cycle()
    await case_no_event_no_cycle()
    await case_refresh_is_not_delayed()


asyncio.run(main())
print("TUTTO OK")
