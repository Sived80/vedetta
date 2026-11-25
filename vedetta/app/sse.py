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
    nxt = None
    try:
        while True:
            if nxt is None:
                nxt = asyncio.ensure_future(anext(stream))
            done, _ = await asyncio.wait({nxt}, timeout=every)
            if not done:
                yield KEEPALIVE
                continue
            try:
                item = nxt.result()
            except StopAsyncIteration:
                return
            nxt = None
            yield item
    finally:
        if nxt is not None and not nxt.done():
            nxt.cancel()
            await asyncio.gather(nxt, return_exceptions=True)
        await stream.aclose()
