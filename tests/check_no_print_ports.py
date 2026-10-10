"""A network printer prints whatever arrives on its raw printing port (HP JetDirect, 9100-9107; LPD, 515): a user found two sheets with "GET / HTTP/1.0 Host: 192.168.1.115" printed by the search of Vedetta, which
sent a plain HTTP GET (and, when the answer was not HTTP, a TLS hello) to every open port to see which ones are web interfaces. nmap itself never probes 9100-9107 for the same reason. What this test fixes:
  - no connection is made to a printing port, and nothing is written to it: not by number (9100-9107, 515) and not by the service name that nmap read (jetdirect, printer, pdl-datastream, lpd...) on any port;
  - the web ports (also the unusual ones, and 631, the web interface of the printer) are still checked, with the GET;
  - the nmap scripts that look at certificates (ssl-cert) are not pointed at a printing port either, even when it says it speaks TLS.
The ports that are skipped are marked as "no web interface" like any port where no HTTP server answered."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import scanner as scan_web  # noqa: E402
scan_nmap = scan_web   # (in this version the web check and the certificate scripts are in the same module)

CONNECTED: list = []
WRITTEN: list = []


class FakeReader:
    async def read(self, n):
        return b""


class FakeWriter:
    def __init__(self, port):
        self.port = port

    def write(self, data):
        WRITTEN.append((self.port, data))

    async def drain(self):
        pass

    def close(self):
        pass

    async def wait_closed(self):
        pass

    def get_extra_info(self, name):
        return None


async def fake_open_connection(host, port, ssl=None, **kw):
    CONNECTED.append((host, port, ssl is not None))
    return FakeReader(), FakeWriter(port)


PRINT = [{"port": 9100, "service": "jetdirect"}, {"port": 9101, "service": "unknown"}, {"port": 9107, "service": ""}, {"port": 515, "service": "printer"},
         {"port": 20000, "service": "jetdirect"}, {"port": 20001, "service": "pdl-datastream"}, {"port": 20002, "service": "lpd"}]
WEB = [{"port": 80, "service": "http"}, {"port": 631, "service": "ipp"}, {"port": 8123, "service": "unknown"}, {"port": 9108, "service": ""}, {"port": 3000, "service": None}]
EPHEMERAL = [{"port": 49152, "service": "x"}]

real = asyncio.open_connection
asyncio.open_connection = fake_open_connection
try:
    ports = [dict(p) for p in PRINT + WEB + EPHEMERAL]
    asyncio.run(scan_web._confirm_http_ports("10.0.0.5", ports))
finally:
    asyncio.open_connection = real

printing = {p["port"] for p in PRINT}
touched = {port for _host, port, _tls in CONNECTED}
assert not (touched & printing), "a connection was made to a printing port: %s" % sorted(touched & printing)
assert not [w for w in WRITTEN if w[0] in printing], "something was written to a printing port"
assert touched == {80, 631, 8123, 9108, 3000}, "the web ports are still checked (and only those): %s" % sorted(touched)
assert all(w[1].startswith(b"GET / HTTP/1.0") for w in WRITTEN), "the web ports get the GET"
for p in ports:
    if p["port"] in printing:
        assert p["http_body_size"] is None and p["web_ui"] is False and p["web_scheme"] == "http", ("skipped port not marked as 'no web interface'", p)

# the direct check of one port also refuses a printing port (a caller that does not go through the list)
del CONNECTED[:]
asyncio.open_connection = fake_open_connection
try:
    assert asyncio.run(scan_web._confirm_http_port("10.0.0.5", 9100)) is None
finally:
    asyncio.open_connection = real
assert not CONNECTED, "_confirm_http_port connected to 9100"

# the nmap scripts that read certificates: never on a printing port
seen_args: list = []


async def fake_run_nmap(args, semaphore=None):
    seen_args.append(list(args))
    return ""


real_run = scan_nmap._run_nmap
scan_nmap._run_nmap = fake_run_nmap
try:
    asyncio.run(scan_nmap.tls_ssh_scan("10.0.0.5", [{"port": 443, "service": "https"}, {"port": 9100, "service": "ssl"}, {"port": 9443, "service": ""}, {"port": 22, "service": "ssh"},
                                                    {"port": 515, "service": "ssl"}, {"port": 7000, "service": "jetdirect-ssl"}]))
finally:
    scan_nmap._run_nmap = real_run
assert seen_args, "tls_ssh_scan did not run nmap for the TLS ports"
listed = seen_args[0][seen_args[0].index("-p") + 1].split(",")
assert listed == ["22", "443", "9443"], "the certificate scripts were pointed at: %s" % listed
print("TUTTO OK")
