"""RULE: never risk commanding a device. Besides printing ports (see check_no_print_ports.py), industrial control ports (S7 102, Modbus 502, DNP3 20000, IEC 104 2404, EtherNet/IP
44818, BACnet 47808, Niagara Fox 1911) and LPD (515) can act on what they receive. Nothing is written to them, nmap does not run service detection (-sV) on them, and they are still
SEEN open (a plain connect, no data) because an open port is evidence and the user can see it.
nmap only skips 9100-9107 by itself; --exclude-ports (nmap 6.49 and later) is the documented way to leave other ports out of a scan."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import pipeline_plan, rescan, rescan_background, scan_common, scan_nmap, scan_web  # noqa: E402

NO_TALK = {102, 502, 515, 1911, 2404, 20000, 44818, 47808} | set(range(9100, 9108))
assert NO_TALK <= scan_common.NO_TALK_PORTS and scan_common.PRINT_PORTS <= scan_common.NO_TALK_PORTS
for port in (80, 443, 22, 8123, 631, 1883):
    assert port not in scan_common.NO_TALK_PORTS, port

# by number and by the service name nmap or we read on it
assert scan_common.is_no_talk_port({"port": 502, "service": ""}) and scan_common.is_no_talk_port({"port": 51000, "service": "modbus"})
assert scan_common.is_no_talk_port({"port": 40000, "service": "iso-tsap"}) and scan_common.is_no_talk_port({"port": 9100, "service": "jetdirect"})
assert not scan_common.is_no_talk_port({"port": 80, "service": "http"}) and not scan_common.is_no_talk_port({"port": 631, "service": "ipp"})

# the exclusion that goes with every version detection
args = scan_common.version_exclusion()
assert args[0] == "--exclude-ports" and {int(p) for p in args[1].split(",") if "-" not in p} >= {102, 502, 515, 1911, 2404, 20000, 44818, 47808}

# 1) the planned deep scan: -sV always with the exclusion, no -sV no exclusion
with_sv = pipeline_plan.compose_nmap_args(["ports_fast", "service_os", "http_title"], "10.0.0.5")
assert "-sV" in with_sv and "--exclude-ports" in with_sv, with_sv
assert with_sv[with_sv.index("--exclude-ports") + 1] == args[1]
assert "--exclude-ports" not in (pipeline_plan.compose_nmap_args(["ports_fast"], "10.0.0.5") or []), "no -sV, nothing to exclude: the port scan must still see them"

# 2) the targeted scan of slow devices and 3) the background service reading
seen: list = []


async def fake_run_nmap(call_args, semaphore=None):
    seen.append(list(call_args))
    return ""


real_run = scan_nmap._run_nmap
scan_nmap._run_nmap = fake_run_nmap
try:
    asyncio.run(scan_nmap.fast_ports("10.0.0.5"))
finally:
    scan_nmap._run_nmap = real_run
sv_calls = [c for c in seen if "-sV" in c]
assert sv_calls and all("--exclude-ports" in c for c in sv_calls), seen

captured: list = []


async def fake_background(ip, call_args):
    captured.append(list(call_args))
    return []


real_bg = rescan_background._background_nmap
rescan_background._background_nmap = fake_background
try:
    info = {"ports": [{"port": 80, "service": "http", "label": "80 · http"}, {"port": 502, "service": "modbus", "label": "502 · modbus"},
                      {"port": 515, "service": "printer", "label": "515 · printer"}, {"port": 8123, "service": "", "label": "8123"}]}
    asyncio.run(rescan_background._read_services(info, "10.0.0.5"))
finally:
    rescan_background._background_nmap = real_bg
assert captured, "the background service reading did not run"
listed = captured[0][captured[0].index("-p") + 1].split(",")
assert listed == ["80", "8123"], "service detection was pointed at: %s" % listed

# the plain connect that still sees them open: no service detection, no data, only these ports
del seen[:]
scan_nmap._run_nmap = fake_run_nmap
try:
    asyncio.run(scan_nmap.no_talk_open_ports("10.0.0.5"))
finally:
    scan_nmap._run_nmap = real_run
assert seen and "-sT" in seen[0] and "-sV" not in seen[0] and "-sC" not in seen[0], seen
assert set(seen[0][seen[0].index("-p") + 1].split(",")) == {str(p) for p in scan_common.NO_REQUEST_PORTS}
assert scan_nmap.with_no_talk_ports([{"port": 80}], [{"port": 502}, {"port": 80}]) == [{"port": 80}, {"port": 502}]

# 4) nothing is written to these ports by the web and certificate checks either
WRITTEN: list = []
CONNECTED: list = []


class Writer:
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


class Reader:
    async def read(self, n):
        return b""


async def fake_open_connection(host, port, ssl=None, **kw):
    CONNECTED.append(port)
    return Reader(), Writer(port)


ports = [{"port": p, "service": "x"} for p in (102, 502, 1911, 2404, 20000, 44818, 47808)] + [{"port": 80, "service": "http"}]
real = asyncio.open_connection
asyncio.open_connection = fake_open_connection
try:
    asyncio.run(scan_web._confirm_http_ports("10.0.0.5", ports))
finally:
    asyncio.open_connection = real
assert set(CONNECTED) == {80}, "the web check touched: %s" % sorted(set(CONNECTED))
assert not [w for w in WRITTEN if w[0] != 80]

scan_nmap._run_nmap = fake_run_nmap
del seen[:]
try:
    asyncio.run(scan_nmap.tls_ssh_scan("10.0.0.5", [{"port": 443, "service": "https"}, {"port": 502, "service": "ssl"}, {"port": 44818, "service": "ssh"}]))
finally:
    scan_nmap._run_nmap = real_run
assert seen and seen[0][seen[0].index("-p") + 1].split(",") == ["443"], seen
print("TUTTO OK")
