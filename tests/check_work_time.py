"""The time a deep search of one device really worked (scan/work_time.py). All the devices of a search start together and wait for the two slots of nmap, so "scanned in 352 s" said how long the search had
been going, not how long the device took (about 10 s). Every nmap run of a device is noted while it runs (a context variable that the tasks of the device share), and the log says the elapsed time and,
next to it, the time in which at least one nmap of the device was running (overlapping runs counted once)."""
import asyncio
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import scan_nmap, work_time  # noqa: E402

run = lambda c: asyncio.new_event_loop().run_until_complete(c)   # noqa: E731

# --- the busy time is the union of the runs: overlaps count once, gaps do not count
assert work_time.busy_seconds([]) == 0
assert work_time.busy_seconds([(0, 4)]) == 4
assert work_time.busy_seconds([(0, 4), (2, 6)]) == 6, "overlap"
assert work_time.busy_seconds([(0, 4), (10, 12)]) == 6, "a gap (the wait of the queue) is not work"
assert work_time.busy_seconds([(10, 12), (0, 4), (3, 5)]) == 7, "in any order"
assert work_time.busy_seconds([(0, 10), (2, 3)]) == 10, "a run inside another"

# --- the words of the log: elapsed first, then the work
assert work_time.describe(352.4, 9.2) == "352s, di cui 9s di lavoro", work_time.describe(352.4, 9.2)
assert work_time.describe(12.0, 12.0) == "12s", "no queue: one number is enough"
assert work_time.describe(12.4, 11.9) == "12s", "less than a second of difference is not a queue"
assert work_time.describe(3.0, 0.0) == "3s, di cui 0s di lavoro"
assert work_time.describe(13.0, 12.0) == "13s, di cui 12s di lavoro", "exactly one second of wait is shown"

# --- nothing is noted outside a tracker, and a tracker collects what the tasks it starts note (a task copies the context but shares the list)
work_time.note(1, 2)      # no tracker: nothing happens, no error


async def child(a, b):
    work_time.note(a, b)


async def tracked():
    with work_time.track() as runs:
        await asyncio.gather(child(0, 3), child(2, 5))
    return runs


assert sorted(run(tracked())) == [(0, 3), (2, 5)]
with work_time.track():          # in this very context (a task would have a copy): the tracker is set inside the block and gone when it ends
    assert work_time.RUNS.get() is not None
assert work_time.RUNS.get() is None, "the tracker is gone when the block ends"

# --- a real _run_nmap notes its own run (start and end), also when the process fails; the wait for the slot is not part of it
class Proc:
    def __init__(self, fail):
        self.fail = fail

    async def communicate(self):
        await asyncio.sleep(0.05)
        if self.fail:
            raise ValueError("broken pipe in the test")
        return b"<nmaprun/>", b""

    def kill(self):
        pass

    async def wait(self):
        pass


def fake(fail):
    async def make(*cmd, **kw):
        return Proc(fail)
    return make


real = asyncio.create_subprocess_exec


async def one_run(fail):
    with work_time.track() as runs:
        try:
            await scan_nmap._run_nmap(["-T4", "10.0.0.9"])
        except ValueError:
            pass
    return runs


try:
    asyncio.create_subprocess_exec = fake(False)
    runs = run(one_run(False))
    assert len(runs) == 1 and 0.04 <= runs[0][1] - runs[0][0] < 1.0, runs
    asyncio.create_subprocess_exec = fake(True)
    runs = run(one_run(True))
    assert len(runs) == 1 and runs[0][1] >= runs[0][0], "a failing run is noted too"
finally:
    asyncio.create_subprocess_exec = real
print("check_work_time OK")
