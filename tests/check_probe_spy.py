"""One spy over the lowest level of the network (asyncio.open_connection, sockets, httpx) for every probe that talks to a device: whatever the ports of the device are, nothing is connected, written or
requested on a printing, industrial or control port (rule: never risk commanding a device). The probes are driven with all of those ports open, by number and by the service name, and with the hostile
shapes that came up in the global review. A plain connect (no data) is allowed on the extra control ports and in the two documented exceptions (the latency measure and the «seen open» check); never on a printing or industrial port, and nothing is
ever written or requested on any of them."""
import asyncio
import os
import socket
import sys

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import discovery, localapi, scan_common, scan_web  # noqa: E402
from app.scan.adapters import generic, shelly_gen1, shelly_gen2  # noqa: E402

FORBIDDEN = sorted(scan_common.NO_REQUEST_PORTS)
TOUCHED: list = []
WRITES: list = []     # every write, to prove that the spy sees the allowed traffic too (a spy that sees nothing proves nothing)


class Writer:
    def __init__(self, port):
        self.port = port

    def write(self, data):
        WRITES.append(self.port)
        if self.port in scan_common.NO_REQUEST_PORTS:
            TOUCHED.append(("write", self.port))

    async def drain(self):
        pass

    def close(self):
        pass

    async def wait_closed(self):
        pass

    def get_extra_info(self, name):
        return None


class Reader:
    async def read(self, n):
        return b""


async def spy_open(host, port, **kw):
    if port in scan_common.NO_TALK_PORTS:         # a plain connect (no data) to the extra control ports is allowed; to the printing and industrial ones it is not
        TOUCHED.append(("connect", port))
    return Reader(), Writer(port)


async def spy_send(self, request, **kw):
    if request.url.port in scan_common.NO_REQUEST_PORTS:
        TOUCHED.append(("http", request.url.port))
    return httpx.Response(404, request=request)


def spy_socket(self, address, *a, **k):
    if isinstance(address, tuple) and address[1] in scan_common.NO_TALK_PORTS:
        TOUCHED.append(("socket", address[1]))
    raise OSError("spy")


async def drive():
    real = socket.socket.connect, socket.socket.connect_ex
    socket.socket.connect = socket.socket.connect_ex = spy_socket      # only once the loop exists: the loop itself connects a socket pair when it is created
    try:
        await drive_probes()
    finally:
        socket.socket.connect, socket.socket.connect_ex = real


async def drive_probes():
    for port in FORBIDDEN:
        await generic.probe("10.0.0.5", port)
        await shelly_gen1.probe("10.0.0.5", port)
        await shelly_gen2.battery_probe("10.0.0.5", port)
    for port in FORBIDDEN:
        await discovery.rtsp_probe("10.0.0.5", port)
        await scan_web._confirm_http_port("10.0.0.5", port)
    await localapi.probe("10.0.0.5", FORBIDDEN)
    ports = [{"port": p, "service": s} for p in FORBIDDEN for s in ("unknown", "http", "")] + [{"port": 80, "service": "http"}]
    await scan_web._confirm_http_ports("10.0.0.5", ports)


real_open, real_send = asyncio.open_connection, httpx.AsyncClient.send
asyncio.open_connection, httpx.AsyncClient.send = spy_open, spy_send
try:
    asyncio.run(drive())
finally:
    asyncio.open_connection, httpx.AsyncClient.send = real_open, real_send
assert 80 in WRITES, "the spy saw no request to the web port: it is not watching"
assert not TOUCHED, "a probe touched a forbidden port: %s" % sorted(set(TOUCHED))
print("TUTTO OK")
