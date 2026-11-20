"""The queue of the notifications (the Sentinel's way out, ha_notify): every message goes to the recipients in their order (the first,
the second, the third...), each one after its wait ("delay_s") from the one before, whether the one before took it or not. The
messages wait in line: one is handed out to everybody before the next one starts, so the order is kept. The queue lives in memory:
a restart of the app forgets what was still waiting (an alert of a cycle is not worth more than the next cycle). The last answer of
each recipient is kept for the page (status()); a refusal is said once in the log, not for every message."""
import asyncio
import time
from collections import deque

from ..applog import logger

MAX_WAITING = 50          # more than this waiting: the oldest is dropped (said in the log); a list of down devices is not a backlog
_jobs: deque = deque()
_worker: set = set()      # the running worker (0 or 1), kept alive here
_busy: list = [0]         # messages being handed out right now (0 or 1)
_last: dict = {}          # service -> {"at", "ok", "error"?}
_said: set = set()


def steps(order: list[dict]) -> list[tuple[int, str]]:
    """Pure: [(seconds to wait before, service)] in the order; the first never waits."""
    return [(0 if n == 0 else int(r["delay_s"]), r["service"]) for n, r in enumerate(order)]


def put(message: str, order: list[dict], send) -> int:
    """Puts a message in line for the recipients of `order`; `send(service, message)` is the coroutine that hands it to one of
    them. Returns how many messages are waiting (this one included). Must run inside the event loop."""
    if not order or not message:
        return waiting()
    if len(_jobs) >= MAX_WAITING:
        _jobs.popleft()
        logger.warning("Coda degli avvisi piena: tolto il messaggio più vecchio")
    _jobs.append((message, steps(order), send))
    if all(t.done() for t in _worker):      # a worker that has just finished is still in the set until its callback runs: it takes nothing more
        task = asyncio.create_task(_work())
        _worker.add(task)
        task.add_done_callback(_worker.discard)
    return waiting()


def waiting() -> int:
    return len(_jobs) + _busy[0]


def status() -> dict:
    """For the page: how many messages are waiting and the last answer of every recipient."""
    return {"waiting": waiting(), "last": {k: dict(v) for k, v in _last.items()}}


async def _work() -> None:
    while _jobs:
        message, plan, send = _jobs.popleft()
        _busy[0] = 1
        try:
            for wait_s, service in plan:
                await asyncio.sleep(wait_s)
                await _hand(send, service, message)
        finally:
            _busy[0] = 0


async def _hand(send, service: str, message: str) -> None:
    """One recipient: its answer is kept; a failure does not stop the others."""
    try:
        await send(service, message)
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"[:200]
        _last[service] = {"at": time.time(), "ok": False, "error": reason}
        if (service, reason) not in _said:
            _said.add((service, reason))
            logger.warning("Avviso non consegnato a %s (%s)", service, reason)
        return
    _last[service] = {"at": time.time(), "ok": True}
    _said.difference_update({s for s in _said if s[0] == service})


async def try_now(send, service: str, message: str) -> dict:
    """The «Try» of one recipient: handed at once, outside the line; its answer, as status() reports it."""
    await _hand(send, service, message)
    return dict(_last[service])


def reset() -> None:
    """For the tests: an empty queue and no answers."""
    _jobs.clear()
    _last.clear()
    _said.clear()
    _busy[0] = 0
