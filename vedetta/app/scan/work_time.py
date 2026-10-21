"""work_time: how long a deep search of one device really worked. The devices of a search start together and wait for the slots of nmap, so the elapsed time of a device says how long the search has
been going. Each nmap run is noted here while it runs, in a list that the tasks of the device share (a context variable), and the log gives the elapsed time next to the time of the work."""
import contextlib
import contextvars
import time

RUNS: contextvars.ContextVar[list | None] = contextvars.ContextVar("nmap_runs", default=None)


@contextlib.contextmanager
def track():
    """Collects, for the length of the block, the (start, end) of every nmap run noted by the tasks started inside it."""
    runs: list[tuple[float, float]] = []
    token = RUNS.set(runs)
    try:
        yield runs
    finally:
        RUNS.reset(token)


@contextlib.asynccontextmanager
async def running():
    """The run of one nmap: noted when it ends, however it ends (the wait for the slot is before it and is not part of it). Asynchronous, to stand next to the slot in one `async with`."""
    start = time.monotonic()
    try:
        yield
    finally:
        note(start, time.monotonic())


def note(start: float, end: float) -> None:
    runs = RUNS.get()
    if runs is not None:
        runs.append((start, end))


def busy_seconds(runs: list[tuple[float, float]]) -> float:
    """The time in which at least one run was going: overlaps are counted once, the gaps (the wait for a slot) not at all."""
    total, reach = 0.0, None
    for start, end in sorted(runs):
        if reach is None or start > reach:
            total += end - start
            reach = end
        elif end > reach:
            total += end - reach
            reach = end
    return total


def describe(elapsed: float, busy: float) -> str:
    """The words of the log: the elapsed time and, when the device waited, how much of it was work."""
    if elapsed - busy < 1:
        return f"{elapsed:.0f}s"
    return f"{elapsed:.0f}s, di cui {busy:.0f}s di lavoro"
