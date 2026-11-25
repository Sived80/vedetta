"""sse: moved out of main.py (see tools/split_module.py)."""
import asyncio
import json


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


# Without these headers some browsers/proxies may buffer the response
# instead of delivering it a piece at a time, defeating the streaming.
SSE_HEADERS = {"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}

KEEPALIVE = ": keepalive\n\n"      # an SSE comment: the browser's reader skips it (only "data: " lines are events)


async def with_keepalive(stream, every: float):
    """The items of the async generator `stream`, with a KEEPALIVE line whenever the next one takes longer than `every` seconds: a silent stream is
    kept open through proxies, and the page can tell a slow search from a lost connection. Closing this generator closes `stream` too."""
    pending: list = []          # the task reading the next item, for the cleanup
    try:
        async for item in _paced(stream, every, pending):
            yield item
    finally:
        await _stop(pending, stream)


async def _paced(stream, every: float, pending: list):
    while True:
        if not pending:
            pending.append(asyncio.ensure_future(anext(stream)))
        done, _ = await asyncio.wait(pending, timeout=every)
        if not done:
            yield KEEPALIVE
            continue
        task = pending.pop()
        if isinstance(task.exception(), StopAsyncIteration):
            return
        yield task.result()


async def _stop(pending: list, stream) -> None:
    """The read still waiting is cancelled (the search stream sees its own cancellation), then the stream is closed."""
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    await stream.aclose()
