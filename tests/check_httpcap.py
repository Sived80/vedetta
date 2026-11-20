"""HTTP answers of the devices are read with a ceiling (scan/httpcap.py): a device decides how much it sends, and a descriptor or a
status page of megabytes (a broken firmware, a hostile host) must not be read whole into memory. The ceiling counts the bytes after
the decompression: a small gzip that unpacks to megabytes is refused too. Within the ceiling the answer reads as before (text with
its charset, json). The callers: the Shelly adapter says offline, an SSDP descriptor too large is skipped.
    python tests/check_httpcap.py"""
import asyncio
import gzip
import json
import os
import sys
import tempfile

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
import httpx  # noqa: E402
from app.scan import discovery, httpcap  # noqa: E402
from app.scan.adapters import shelly_gen1  # noqa: E402

BIG = b"x" * (httpcap.DEFAULT_LIMIT + 1)
PAD = b" " * httpcap.DEFAULT_LIMIT
# well-formed answers made too large: the old code read them whole and believed them
BIG_STATUS = b'{"mac": "AABBCCDDEEFF", "uptime": 5, "name": "Big"' + PAD + b"}"
BIG_DESCR = b"<root><device><friendlyName>Big</friendlyName>" + PAD + b"</device></root>"


def answer(request):
    path = request.url.path
    if path == "/big":
        return httpx.Response(200, content=BIG)
    if path == "/bigdescr":
        return httpx.Response(200, content=BIG_DESCR)
    if path == "/bomb":
        return httpx.Response(200, content=gzip.compress(b"{" + b" " * (2 * httpcap.DEFAULT_LIMIT) + b"}"), headers={"Content-Encoding": "gzip"})
    if path == "/latin":
        return httpx.Response(200, content="Cucina è".encode("latin-1"), headers={"Content-Type": "text/plain; charset=iso-8859-1"})
    if path == "/json":
        return httpx.Response(200, content=json.dumps({"mac": "AABBCCDDEEFF", "uptime": 5}).encode())
    if path == "/bad-charset":
        return httpx.Response(200, content=b"ok", headers={"Content-Type": "text/plain; charset=made-up"})
    return httpx.Response(404, content=b"no")


def client():
    return httpx.AsyncClient(transport=httpx.MockTransport(answer))


async def get(path, limit=httpcap.DEFAULT_LIMIT):
    async with client() as c:
        return await httpcap.get(c, "http://10.0.0.5" + path, limit)


def refused(path):
    try:
        asyncio.run(get(path))
    except httpcap.TooLarge:
        return True
    return False


# 1) beyond the ceiling: refused, plain or compressed
assert refused("/big") and refused("/bomb")
assert issubclass(httpcap.TooLarge, ValueError)        # the callers that drop a malformed answer drop this one too

# 2) within it: as before
r = asyncio.run(get("/json"))
assert r.status_code == 200 and r.json() == {"mac": "AABBCCDDEEFF", "uptime": 5}
assert asyncio.run(get("/latin")).text == "Cucina è"
assert asyncio.run(get("/bad-charset")).text == "ok"
assert asyncio.run(get("/missing")).status_code == 404
try:
    asyncio.run(get("/json", limit=10))
    raise AssertionError("a 10 byte ceiling let a longer body through")
except httpcap.TooLarge:
    pass

# 3) the Shelly adapter: an endless status page is no Shelly
real = httpx.AsyncClient


class Patched(real):
    def __init__(self, *a, **k):
        k["transport"] = httpx.MockTransport(lambda request: httpx.Response(200, content=BIG_STATUS))
        super().__init__(*a, **k)


shelly_gen1.httpx.AsyncClient = Patched
assert asyncio.run(shelly_gen1.probe("10.0.0.5")) == {"online": False}
shelly_gen1.httpx.AsyncClient = real


# 4) an SSDP descriptor too large is skipped, a normal one read
async def describe():
    async with client() as c:
        return await discovery._describe_ssdp(c, "10.0.0.5", ["http://10.0.0.5/bigdescr", "http://10.0.0.5/latin"])

ip, merged = asyncio.run(describe())
assert ip == "10.0.0.5" and merged == {"types": []}, merged
print("check_httpcap: ok")
