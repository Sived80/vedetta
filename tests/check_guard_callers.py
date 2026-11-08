"""The three places that keep a scan inside the network (the deep search of chosen addresses, the rescan of chosen cards, the nightly rescan of
old cards), with the REAL guard and a fake `ip addr`: an address of the network is kept, one of another network or a public one is left out and
named in the log, a list with nothing outside logs nothing. Written before moving them from netutil.filter_local_ips to networks.registry, so
that the move is proved not to change what they do. Invented private addresses only.
    python tests/check_guard_callers.py"""
import asyncio
import logging
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import maintenance, netutil  # noqa: E402
from app.applog import logger  # noqa: E402
from app.routes import device_routes, scan_routes  # noqa: E402


class FakeProc:
    returncode = 0

    async def communicate(self, data=None):
        return b"3: lan9    inet 192.168.50.7/24 brd 192.168.50.255 scope global lan9\n", b""


async def fake_exec(*args, **kwargs):
    return FakeProc()


netutil.asyncio.create_subprocess_exec = fake_exec
netutil.lan_iface = lambda: "lan9"
LINES: list = []


class Catch(logging.Handler):
    def emit(self, record):
        if record.levelno >= logging.WARNING:
            LINES.append(record.getMessage())


logger.addHandler(Catch())
INSIDE, OTHER, PUBLIC = "192.168.50.10", "192.168.60.10", "198.51.100.7"
CARDS = [{"id": "a", "ip": INSIDE, "name": "a"}, {"id": "b", "ip": OTHER, "name": "b"}, {"id": "c", "ip": PUBLIC, "name": "c"}]
device_routes.devices_config.load_devices = lambda: CARDS
maintenance.last_deep_attempt = lambda d: 0


def warned(*ips) -> bool:
    return any(line.startswith("Scansione rifiutata, IP fuori dalla rete locale 192.168.50.0/24: ") and all(ip in line for ip in ips) for line in LINES)


# 1) deep search of chosen addresses (POST /api/scan/deep): what reaches the pipeline
class Stop(Exception):
    pass


ASKED: list = []


def capture(ips, hints):
    ASKED.append(list(ips))
    raise Stop


class FakeRequest:
    def __init__(self, body):
        self.body = body
        self.headers = {}
        self.query_params = {}
        self.cookies = {}

    async def json(self):
        return self.body


scan_routes.pipeline.start_associative = capture
for ips, kept, out in (([INSIDE, OTHER, PUBLIC, "not an address"], [INSIDE], (OTHER, PUBLIC)), ([INSIDE], [INSIDE], ())):
    LINES.clear()
    ASKED.clear()
    try:
        asyncio.run(scan_routes.api_scan_deep(FakeRequest({"ips": ips})))
    except Stop:
        pass
    assert ASKED == [kept], ASKED
    assert warned(*out) if out else not LINES, LINES

# 2) rescan of chosen cards (POST /api/devices/rescan) and 3) nightly rescan of old cards
for name, call in (("rescan", lambda: device_routes._local_devices_of({"a", "b", "c"})), ("nightly", maintenance._stale_local_devices)):
    LINES.clear()
    got = asyncio.run(call())
    assert [d["ip"] for d in got] == [INSIDE], (name, got)
    assert warned(OTHER, PUBLIC), (name, LINES)
CARDS[1:] = []
LINES.clear()
assert [d["ip"] for d in asyncio.run(device_routes._local_devices_of({"a"}))] == [INSIDE] and not LINES, LINES

print("check_guard_callers: ok")
