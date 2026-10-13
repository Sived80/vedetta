"""An address that a device writes in its own answer is not a place to send data to. The SSDP answer carries a LOCATION header; the search used to fetch whatever it said (a GET). A device, or a forged
packet, could name a printer's raw printing port or a controller: the app would send the request there. Rule: never risk commanding a device. The same class of flaw as CallStranger
(CVE-2020-12695: a URL chosen by the peer makes the device open connections to arbitrary targets); no source found on the LOCATION field itself, so the rule is the plain one: the URL must
point at the address that answered, on a port that is not a no-talk port, and a device that must not be touched is not asked at all."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
import httpx  # noqa: E402
from app.scan import discovery as dsc  # noqa: E402
from app.scan import scan_common  # noqa: E402

ok = scan_common.safe_location
# the plain case, with and without a port, http and https
assert ok("http://10.0.0.40:49152/desc.xml", "10.0.0.40") and ok("https://10.0.0.40/desc.xml", "10.0.0.40") and ok("http://10.0.0.40/", "10.0.0.40")
# another host, a name, a user-info trick, a different scheme: no
assert not ok("http://10.0.0.99:80/desc.xml", "10.0.0.40") and not ok("http://printer.local/desc.xml", "10.0.0.40")
assert not ok("http://10.0.0.40@10.0.0.99/x", "10.0.0.40") and not ok("ftp://10.0.0.40/x", "10.0.0.40") and not ok("file:///etc/passwd", "10.0.0.40")
assert not ok("", "10.0.0.40") and not ok("http://", "10.0.0.40") and not ok("//10.0.0.40/x", "10.0.0.40") and not ok(None, "10.0.0.40")
# the same host but a printing or industrial control port: no (also with the port written in other ways)
for port in (9100, 9107, 515, 502, 102, 44818, 47808):
    assert not ok(f"http://10.0.0.40:{port}/desc.xml", "10.0.0.40"), port
assert not ok("http://10.0.0.40:0x1f4/x", "10.0.0.40") and not ok("http://10.0.0.40:99999/x", "10.0.0.40") and not ok("http://10.0.0.40:abc/x", "10.0.0.40")

DESC = ('<root><device><deviceType>urn:schemas-upnp-org:device:MediaRenderer:1</deviceType><friendlyName>Living room TV</friendlyName>'
        '<manufacturer>Acme</manufacturer><modelName>TV-9000</modelName></device></root>')
asked: list = []


def handler(request):
    asked.append(str(request.url))
    return httpx.Response(200, text=DESC)


def packets(items):
    async def fake(factory, payload, dest, own_ip, timeout, label):
        proto = factory()
        for location, ip in items:
            proto.datagram_received(f"HTTP/1.1 200 OK\r\nLOCATION: {location}\r\nST: upnp:rootdevice\r\n\r\n".encode(), (ip, 1900))
        return proto
    return fake


run = lambda c: asyncio.new_event_loop().run_until_complete(c)   # noqa: E731
transport = httpx.MockTransport(handler)

# the protocol keeps only the locations that point at the address that answered
dsc._collect = packets([("http://10.0.0.40:49152/desc.xml", "10.0.0.40"),      # honest
                        ("http://10.0.0.50:9100/", "10.0.0.41"),                # points at a printer's raw port
                        ("http://10.0.0.51:80/desc.xml", "10.0.0.41"),          # points at another host
                        ("http://10.0.0.42:502/d.xml", "10.0.0.42")])           # a controller port on its own address
found = run(dsc.ssdp_devices("10.0.0.2", 0.1, http_transport=transport))
assert list(found) == ["10.0.0.40"] and found["10.0.0.40"]["name"] == "Living room TV", found
assert asked == ["http://10.0.0.40:49152/desc.xml"], "only the honest URL was fetched: %s" % asked

# a device that must not be touched is not asked at all
del asked[:]
dsc._collect = packets([("http://10.0.0.40:49152/desc.xml", "10.0.0.40"), ("http://10.0.0.43:8080/d.xml", "10.0.0.43")])
found = run(dsc.ssdp_devices("10.0.0.2", 0.1, http_transport=transport, skip=frozenset({"10.0.0.43"})))
assert asked == ["http://10.0.0.40:49152/desc.xml"] and list(found) == ["10.0.0.40"], (asked, found)
print("TUTTO OK")
