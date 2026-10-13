"""Contract test of the transports of scan/discovery.py: the multicast listener is replaced by a function that feeds recorded packets to the
real protocol objects, the UPnP descriptors come from an in-memory HTTP server, and the RTSP probe talks to a real server on localhost.
Covers what the pure parsers tests do not: who is kept when several packets arrive, unreachable network, broken answers, silent ports.
The packets are written from the OASIS / UPnP / RTSP formats (an ONVIF camera and a UPnP media renderer), not captured from a device."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
import httpx  # noqa: E402
from app.scan import discovery as dsc  # noqa: E402

PROBE_MATCH = b"""<?xml version="1.0"?><s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
 xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery" xmlns:dn="http://www.onvif.org/ver10/network/wsdl"><s:Body><d:ProbeMatches><d:ProbeMatch>
 <d:Types>dn:NetworkVideoTransmitter tds:Device</d:Types>
 <d:Scopes>onvif://www.onvif.org/name/Garage_Cam onvif://www.onvif.org/hardware/IPC-9000 onvif://www.onvif.org/mfr/Acme onvif://www.onvif.org/location/garage</d:Scopes>
 <d:XAddrs>http://10.0.0.30:80/onvif/device_service</d:XAddrs></d:ProbeMatch></d:ProbeMatches></s:Body></s:Envelope>"""
SSDP_REPLY = b"HTTP/1.1 200 OK\r\nCACHE-CONTROL: max-age=1800\r\nLOCATION: http://10.0.0.40:49152/desc.xml\r\nST: upnp:rootdevice\r\n\r\n"
DESC = ('<root><device><deviceType>urn:schemas-upnp-org:device:MediaRenderer:1</deviceType><friendlyName>Living room TV</friendlyName>'
        '<manufacturer>Acme</manufacturer><modelName>TV-9000</modelName></device></root>')

# --- WS-Discovery: the first answer of each address is kept, garbage is ignored, an unreachable network gives {}
sent = []


def feeding(packets):
    async def fake(factory, payload, dest, own_ip, timeout, label):
        sent.append((payload[:60], dest, own_ip, label))
        proto = factory()
        for data, addr in packets:
            proto.datagram_received(data, addr)
        return proto
    return fake


run = lambda c: asyncio.new_event_loop().run_until_complete(c)   # noqa: E731
dsc._collect = feeding([(PROBE_MATCH, ("10.0.0.30", 3702)), (b"garbage", ("10.0.0.31", 3702)), (PROBE_MATCH.replace(b"Garage_Cam", b"Other"), ("10.0.0.30", 3702))])
found = run(dsc.wsd_scan("10.0.0.2", 0.1))
assert list(found) == ["10.0.0.30"] and found["10.0.0.30"]["name"] == "Garage Cam", "first packet of an address wins, garbage dropped"
assert found["10.0.0.30"]["onvif"] is True and found["10.0.0.30"]["manufacturer"] == "Acme"
assert sent[-1][1] == dsc.WSD_ADDR and sent[-1][2] == "10.0.0.2" and sent[-1][0].startswith(b"<?xml") and sent[-1][3] == "WS-Discovery"


async def no_network(*a, **k):
    return None


dsc._collect = no_network
assert run(dsc.wsd_scan()) == {}

# --- SSDP: locations per address (at most 4), the descriptors read over HTTP, silent or broken ones dropped
dsc._collect = feeding([(SSDP_REPLY, ("10.0.0.40", 1900)), (SSDP_REPLY.replace(b"49152/desc.xml", b"49152/other.xml"), ("10.0.0.40", 1900)),
                        (SSDP_REPLY.replace(b"10.0.0.40", b"10.0.0.41"), ("10.0.0.41", 1900)), (b"HTTP/1.1 200 OK\r\n\r\n", ("10.0.0.42", 1900)),
                        (SSDP_REPLY.replace(b"10.0.0.40", b"10.0.0.43"), ("10.0.0.43", 1900))])
asked = []


def handler(request):
    asked.append(str(request.url))
    if "10.0.0.41" in str(request.url):
        raise httpx.ConnectError("refused")
    if "10.0.0.43" in str(request.url):
        return httpx.Response(200, text="<root/>")
    return httpx.Response(200, text=DESC)


devices = run(dsc.ssdp_devices("10.0.0.2", 0.1, http_transport=httpx.MockTransport(handler)))
assert devices == {"10.0.0.40": {"types": ["MediaRenderer"], "name": "Living room TV", "manufacturer": "Acme", "model": "TV-9000"}}, devices
assert sorted(a for a in asked if "10.0.0.40" in a) == ["http://10.0.0.40:49152/desc.xml", "http://10.0.0.40:49152/other.xml"]
assert not any("10.0.0.42" in a for a in asked), "an answer without Location is not fetched"
dsc._collect = no_network
assert run(dsc.ssdp_devices(http_transport=httpx.MockTransport(handler))) == {}

# --- RTSP: a real server on localhost
async def rtsp_scenarios():
    replies = {}

    async def serve(reader, writer):
        await reader.readuntil(b"\r\n\r\n")
        data = replies["data"]
        if data is not None:
            writer.write(data)
            await writer.drain()
        if replies.get("hang"):
            await asyncio.sleep(5)
        writer.close()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        replies["data"] = b"RTSP/1.0 200 OK\r\nCSeq: 1\r\nServer: Hipcam RealServer/V1.0\r\nPublic: OPTIONS, DESCRIBE, SETUP\r\n\r\n"
        out = await dsc.rtsp_probe("127.0.0.1", port, 1.0)
        assert out == {"rtsp": True, "rtsp_server": "Hipcam RealServer/V1.0", "rtsp_methods": "OPTIONS, DESCRIBE, SETUP"}, out
        replies["data"] = b"HTTP/1.1 400 Bad Request\r\n\r\n"
        assert await dsc.rtsp_probe("127.0.0.1", port, 1.0) == {}, "a web server on the port is not RTSP"
        replies["data"] = None
        assert await dsc.rtsp_probe("127.0.0.1", port, 1.0) == {}, "closed without answering"
        replies.update(data=b"RTSP/1.0 200 OK\r\n", hang=True)
        assert await dsc.rtsp_probe("127.0.0.1", port, 0.3) == {}, "an answer that never ends is cut at the timeout"
    assert await dsc.rtsp_probe("127.0.0.1", port, 0.5) == {}, "nothing listening"


run(rtsp_scenarios())
print("TUTTO OK")
