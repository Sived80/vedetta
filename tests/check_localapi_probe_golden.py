"""Golden-master test of localapi.probe (asks only the manufacturer interfaces of the open ports; the first answer with the expected shape wins): 3000 generated hosts. The network is
replaced by httpx.MockTransport driven by a random script - for every URL of the plan a refusal, an error status, a good answer of that interface (falsy fields included), a wrong-shaped or
non-JSON answer; for the ESPHome stream a wrong status or content type, a stream with a "ping" event with and without a title, junk, a broken data line, and an endless stream without a ping
(more than 4096 bytes, in chunks) - with open-port sets of every kind (list, tuple, set, repeated ports, no useful port, all of them). The returned dictionary (key order included) and the list
of requests that reached the transport (the order counts) must match tests/golden/localapi_probe.json, written from the code as it was before the function was split.
Regenerate only on purpose:  LOCALAPI_GOLDEN_UPDATE=1 python tests/check_localapi_probe_golden.py"""
import asyncio
import json
import os
import random
import sys
from pathlib import Path

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import localapi  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "localapi_probe.json"
REAL_TIMEOUT = localapi._TIMEOUT
N = 3000
rng = random.Random(27182818)


def pick(seq):
    return seq[rng.randrange(len(seq))]


BODIES = {
    "shelly": ['{"mac":"AABB","type":"SHSW-1","gen":1,"fw":"1.0"}', '{"mac":"A","model":"Plus1","name":"","fw_id":"x","ver":""}', '{"mac":"A","gen":2,"name":"Lamp"}', '{"mac":""}', "not json", "[1]", "null",
               "", '{"type":"SHSW"}', '{"mac":"A","type":"T","name":"N","fw":"F","ver":"V","fw_id":""}'],
    "tasmota": ['{"StatusFWR":{"Version":"12.0","Hardware":"ESP"},"Status":{"FriendlyName":["Lamp"],"DeviceName":""},"StatusNET":{"Hostname":"tas"}}', '{"StatusFWR":{}}', '{"x":1}', "bad",
                '{"StatusFWR":{"Hardware":""},"Status":{"DeviceName":"Dev"}}', '{"StatusFWR":{"Version":"1"},"Status":{"FriendlyName":[]}}', '{"StatusFWR":null,"Status":null}', "[]",
                '{"StatusFWR":{"Version":"1"},"Status":5}'],
    "sonos": ["<root><device><friendlyName>Salotto</friendlyName><manufacturer>Sonos, Inc.</manufacturer><modelName>Era 100</modelName></device></root>",
              "<root><device><manufacturer>Other</manufacturer></device></root>", "", "<manufacturer>SONOS</manufacturer>", "<manufacturer>Sonos</manufacturer><modelName></modelName>"],
    "roku": ["<device-info><vendor-name>Roku</vendor-name><model-name>Ultra</model-name><friendly-device-name>TV</friendly-device-name><software-version>12</software-version></device-info>",
             "<device-info><user-device-name>Mine</user-device-name></device-info>", "<device-info/>", "<other/>", "", "<device-info><vendor-name> </vendor-name></device-info>"],
    "cast": ['{"name":"Living","build_version":"1","cast_build_revision":""}', '{"name":"","build_version":""}', "{}", "bad", '{"build_version":"3"}', '{"name":"X","cast_build_revision":"r9"}', "[1]"],
}
EVENTS = ["event: ping\ndata: {\"title\": \"esp-kitchen\", \"x\": 1}\n\n", "event: ping\ndata: {\"title\": \"\"}\n\n", "event: ping\ndata: not json\n\n", "event: state\ndata: {}\n\n",
          "event: ping\r\ndata: {\"title\": \"crlf\"}\r\n\r\n", "event: ping\ndata: [1]\n\n", "retry: 100\n\n", ""]


def url_behavior(kind):
    r = rng.random()
    if r < 0.2:
        return "error"
    if r < 0.3:
        return ("status", pick([404, 500, 204, 301]))
    if r < 0.4:
        return ("body", "junk <html> not the expected thing")
    return ("body", pick(BODIES[kind]))


def esphome_behavior():
    r = rng.random()
    if r < 0.03:
        return ("slow",)  # the stream is slower than the timeout of the whole request: an exception comes out of the gather
    if r < 0.15:
        return ("error",)
    if r < 0.25:
        return ("status", pick([404, 500]))
    if r < 0.35:
        return ("wrongtype", pick(["text/html", "", "application/json"]))
    if r < 0.5:
        return ("endless", pick([1000, 1500, 400]))  # chunks without a ping: the 4096 bytes limit
    chunks = [pick(EVENTS)]
    if rng.random() < 0.4:
        chunks = [chunks[0][:rng.randrange(0, 20)], chunks[0][rng.randrange(0, 20):]]  # the event split across chunks (or damaged)
    if rng.random() < 0.3:
        chunks.append(pick(EVENTS))
    return ("events", chunks)


class SlowChunks(httpx.AsyncByteStream):
    async def __aiter__(self):
        await asyncio.sleep(0.3)
        yield b'event: ping\ndata: {"title": "late"}\n\n'


class Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks

    async def __aiter__(self):
        for c in self.chunks:
            yield c.encode() if isinstance(c, str) else c


def make_handler(ip, script, seen):
    def handler(request):
        url = str(request.url)
        seen.append(url)
        if url.endswith("/events"):
            b = script["esphome"]
            if b[0] == "error":
                raise httpx.ConnectError("no route")
            if b[0] == "slow":
                return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=SlowChunks())
            if b[0] == "status":
                return httpx.Response(b[1], headers={"content-type": "text/event-stream"}, content=b"")
            if b[0] == "wrongtype":
                return httpx.Response(200, headers={"content-type": b[1]}, stream=Chunks(["event: ping\ndata: {\"title\": \"zz\"}\n\n"]))
            if b[0] == "endless":
                return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Chunks(["x" * b[1]] * 8))
            return httpx.Response(200, headers={"content-type": "text/event-stream; charset=utf-8"}, stream=Chunks(b[1]))
        if url.endswith("/elsewhere"):  # where the redirects point: a good Shelly answer, which nobody asked for
            return httpx.Response(200, text=BODIES["shelly"][0])
        b = script["urls"][url]
        if b == "error":
            raise httpx.ConnectError("refused")
        if b[0] == "status":
            return httpx.Response(b[1], text="whatever", headers={"location": "http://%s/elsewhere" % ip} if b[1] == 301 else {})
        return httpx.Response(200, text=b[1])
    return handler


ALL_PORTS = [22, 80, 443, 1400, 8060, 8008, 8123, 554]
out = []
stats = {"empty": 0, "shelly": 0, "tasmota": 0, "sonos": 0, "roku": 0, "cast": 0, "esphome": 0, "none_found": 0, "request": 0, "exc": 0, "filtered": 0, "stream_req": 0, "slow": 0}
for _ in range(N):
    ip = pick(["192.168.1.20", "10.0.0.9"])
    r = rng.random()
    if r < 0.1:
        ports = pick([[], (), set(), [22, 443], [8123]])
    else:
        ports = [p for p in ALL_PORTS if rng.random() < 0.45]
        if rng.random() < 0.15:
            ports = ports + ports[:2]
        ports = pick([list, tuple, set, frozenset])(ports)
    urls = {}
    for kind, url in localapi.plan(ip, ports):
        urls[url] = url_behavior(kind)
    if rng.random() < 0.35:  # nothing else answers: the ESPHome stream (the last of the plan) is the one that decides
        urls = {u: pick(["error", ("status", 404)]) for u in urls}
    script = {"urls": urls, "esphome": esphome_behavior()}
    seen = []
    localapi._TIMEOUT = 0.05 if script["esphome"][0] == "slow" else REAL_TIMEOUT
    try:
        res = asyncio.run(localapi.probe(ip, ports, transport=httpx.MockTransport(make_handler(ip, script, seen))))
        rec = {"ret": res, "requests": seen}
        src = res.get("api_source")
        if not res:
            stats["none_found"] += 1
        elif src in stats:
            stats[src] += 1
        stats["filtered"] += bool(res) and src != "esphome" and any(k not in res for k in ("api_model", "api_name", "api_fw", "api_vendor", "api_hostname"))
    except Exception as exc:
        rec = {"exception": type(exc).__name__, "requests": seen}
        stats["exc"] += 1
    stats["slow"] += script["esphome"][0] == "slow" and 80 in set(ports)
    stats["empty"] += not seen
    stats["request"] += len(seen)
    stats["stream_req"] += any(u.endswith("/events") for u in seen)
    out.append(rec)

text_out = json.dumps(out)  # no sort_keys: the key order counts
if os.environ.get("LOCALAPI_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.parent.mkdir(exist_ok=True)
    GOLDEN.write_text(text_out, encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want) == len(out) == N
for i, (x, y) in enumerate(zip(out, want)):
    assert json.dumps(x) == json.dumps(y), "case %d differs: %s" % (i, json.dumps([x, y])[:700])
assert text_out == GOLDEN.read_text(encoding="utf-8"), "key order or formatting differs"
assert all(stats[k] > 60 for k in ("empty", "shelly", "tasmota", "sonos", "roku", "cast", "esphome", "none_found", "filtered", "stream_req")) and stats["slow"] > 20, "too uniform: %s" % stats
assert stats["exc"] < 300, stats
print("TUTTO OK")
