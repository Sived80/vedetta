"""The web check sends a text request (GET /, and a TLS hello when the answer is not HTTP) to the open ports. Found by the global review: it did so for EVERY open port that was not in the closed list of
printing and control ports, services that nmap had already named included (ssh, mqtt, telnet, ajp...) and control ports not in the list (OPC UA 4840, OMRON FINS 9600, PCWorx 1962, PROFINET 34962...). A controller on a
port we do not know may read text as a command. Rule: never risk commanding a device. Now the request goes only to a port that can be a web server: nmap named it http-like (http, https, ipp, upnp...) or did not name it
(8123, 3000...), and never to a port of the ICS protocols nmap has scripts for. Nothing is lost: a port that nmap named ssh is not a web interface."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import scan_common, scan_web  # noqa: E402

CONNECTED: list = []
WRITTEN: list = []


class Reader:
    async def read(self, n):
        return b""


class Writer:
    def __init__(self, port):
        self.port = port

    def write(self, data):
        WRITTEN.append(self.port)

    async def drain(self):
        pass

    def close(self):
        pass

    async def wait_closed(self):
        pass

    def get_extra_info(self, name):
        return None


async def spy(host, port, ssl=None, **kw):
    CONNECTED.append(port)
    return Reader(), Writer(port)


def ask(ports):
    del CONNECTED[:], WRITTEN[:]
    real = asyncio.open_connection
    asyncio.open_connection = spy
    try:
        asyncio.run(scan_web._confirm_http_ports("10.0.0.5", [dict(p) for p in ports]))
    finally:
        asyncio.open_connection = real
    return set(CONNECTED)


# web candidates: named http-like, or not named at all
WEB = [{"port": 80, "service": "http"}, {"port": 443, "service": "https"}, {"port": 8443, "service": "https-alt"}, {"port": 631, "service": "ipp"}, {"port": 49000, "service": "upnp"},
       {"port": 8123, "service": "unknown"}, {"port": 3000, "service": ""}, {"port": 9999, "service": None}, {"port": 8080, "service": "http-proxy"}, {"port": 8081, "service": "tcpwrapped"}]
assert ask(WEB) == {80, 443, 8443, 631, 49000, 8123, 3000, 9999, 8080, 8081}, ask(WEB)

# services that nmap already named as something else: no request
NOT_WEB = [{"port": 22, "service": "ssh"}, {"port": 23, "service": "telnet"}, {"port": 21, "service": "ftp"}, {"port": 25, "service": "smtp"}, {"port": 1883, "service": "mqtt"},
           {"port": 8009, "service": "ajp13"}, {"port": 3306, "service": "mysql"}, {"port": 5432, "service": "postgresql"}, {"port": 445, "service": "microsoft-ds"}, {"port": 53, "service": "domain"}]
assert ask(NOT_WEB) == set(), "a request went to a port that is not a web server: %s" % sorted(CONNECTED)
assert not WRITTEN

# a name that nmap only guessed from the port number (the deep search runs without -sV) is not believed, except for the services that read text as commands:
# Home Assistant on 8123 is «polipo», Node-RED on 1880 «vsat-control», Proxmox on 8006 «wpl-analytics» and they are web interfaces (the card of the user lost its link and its brand)
GUESSED = [{"port": 8123, "service": "polipo", "confirmed": False}, {"port": 1880, "service": "vsat-control", "confirmed": False}, {"port": 8006, "service": "wpl-analytics", "confirmed": False}]
assert ask(GUESSED) == {8123, 1880, 8006}, ask(GUESSED)
assert ask([dict(p, confirmed=False) for p in NOT_WEB]) == set(), "a guessed shell, broker or database name was not left alone: %s" % sorted(CONNECTED)
# the same names VERIFIED by nmap are believed: it queried the service and it is not a web server
VERIFIED = [dict(p, confirmed=True) for p in GUESSED] + [dict(p, confirmed=True) for p in NOT_WEB]
assert ask(VERIFIED) == set(), "a request went to a port that nmap verified as not web: %s" % sorted(CONNECTED)
assert ask([{"port": 80, "service": "http", "confirmed": True}, {"port": 8443, "service": "https-alt", "confirmed": True}]) == {80, 8443}

# control ports of the protocols nmap has scripts for, even when nothing named them: no request
ICS = [4840, 9600, 1962, 34962, 34963, 34964, 20547, 2455, 1200, 18245, 5094, 789, 5006, 5007, 102, 502, 2404, 20000, 44818, 47808, 1911, 9100, 515]
assert ask([{"port": p, "service": "unknown"} for p in ICS]) == set(), "a request went to a control port: %s" % sorted(CONNECTED)
assert not WRITTEN

# a mix: only the web ones are asked
assert ask(WEB[:3] + NOT_WEB + [{"port": 4840, "service": "unknown"}]) == {80, 443, 8443}
# the extra control ports are not asked, but they do not make a card «don't touch» by themselves (a port number can be used by something else): only the strongest ones do
from app.scan import touch_policy  # noqa: E402
assert touch_policy.touch_level({"id": "x", "ip": "10.0.0.9", "scan_info": {"ports": [{"label": "4840 · opc-ua"}]}}) == touch_policy.NORMAL
assert touch_policy.touch_level({"id": "x", "ip": "10.0.0.9", "scan_info": {"ports": [{"label": "502"}]}}) == touch_policy.NONE
print("TUTTO OK")
