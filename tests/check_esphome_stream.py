"""The reader of the /events stream of a device (localapi._esphome): the stream stays open for ever on a real device, so it must stop by itself: as soon as the answer is there, or after 4 KiB with nothing in
it, or when the stream ends, or when the page is not an event stream or the request fails. A stream that never stopped would keep a connection and a task open for ever."""
import asyncio
import os
import sys
import tempfile

import httpx

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import localapi  # noqa: E402

PING = b'event: ping\ndata: {"title": "garage-door", "name": "garage-door"}\n\n'
SENT: list = []


def reply(chunks, content_type="text/event-stream", status=200):
    async def body():
        for chunk in chunks:
            SENT.append(len(chunk))
            yield chunk

    def handler(request):
        return httpx.Response(status, headers={"content-type": content_type}, stream=_Async(body()))
    return handler


class _Async(httpx.AsyncByteStream):
    def __init__(self, generator):
        self.generator = generator

    async def __aiter__(self):
        async for chunk in self.generator:
            yield chunk


def endless():
    async def chunks():
        while True:
            yield b": nothing here\n" * 70            # about 1 KiB per chunk
            await asyncio.sleep(0)                    # gives the loop a turn: a reader that never stops is then cut by the time limit of the test instead of freezing it
    return chunks()


async def run(handler):
    del SENT[:]
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        return await asyncio.wait_for(localapi._esphome(client, "10.0.0.5"), 5)


def go(handler):
    return asyncio.run(run(handler))


# 1) the answer is in the first chunk: it is returned and the rest is not read
found = go(reply([PING, b"x" * 1000, b"y" * 1000]))
assert found.get("api_name") == "garage-door", found
assert len(SENT) <= 2, "the stream was read after the answer: %s" % SENT

# 2) the answer comes in the second chunk
assert go(reply([b": hello\n", PING])).get("api_name") == "garage-door"

# 3) nothing in it and it never ends: stops after about 4 KiB (here: a handful of chunks), answer {}
async def never_ending_handler_result():
    async def handler_body():
        async for chunk in endless():
            SENT.append(len(chunk))
            yield chunk

    def handler(request):
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=_Async(handler_body()))
    return await run(handler)


assert asyncio.run(never_ending_handler_result()) == {}, "no answer"
assert sum(SENT) <= 4096 + 2048, "the reading did not stop at 4 KiB: %d bytes" % sum(SENT)

# 4) the stream ends with nothing: {}
assert go(reply([b": nothing\n"])) == {}
# 5) not an event stream, or an error status: {} and nothing read
assert go(reply([PING], content_type="text/html")) == {} and not SENT
assert go(reply([PING], status=404)) == {} and not SENT
# 6) the request fails: {}, never an exception

def broken(request):
    raise httpx.ConnectError("refused")


assert go(broken) == {}
print("TUTTO OK")
