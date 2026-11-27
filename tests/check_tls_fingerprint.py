# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The SHA-256 fingerprint of the TLS certificate (1.0.1): the deep search already fetches the certificate of a web port over TLS
(scan_web._https_get); its fingerprint is kept as `tls_fp` (lower-case hex) next to the subject, carried by the port, by the web identity
(the default web port, else any confirmed TLS port) and by the pipeline into scan_info, and kept where scan_info keys are kept.
It is what tells two addresses of one machine apart from two machines (twins.py): every address of a router presents the same certificate.
    python tests/check_tls_fingerprint.py"""
import asyncio
import hashlib
import os
import sys
import tempfile

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import pipeline_probes, rescan, scan_format, scan_web  # noqa: E402

DER = bytes.fromhex("3003020101") + b"invented-certificate-bytes"
FP = hashlib.sha256(DER).hexdigest()


# 1) _https_get: the fingerprint of the DER the server presented
class SslObj:
    def getpeercert(self, binary_form=False):
        return DER


class Writer:
    def get_extra_info(self, name):
        return SslObj() if name == "ssl_object" else None

    def write(self, data):
        pass

    async def drain(self):
        pass

    def close(self):
        pass

    async def wait_closed(self):
        pass


class Reader:
    async def read(self, n):
        return b"HTTP/1.1 200 OK\r\nServer: test\r\n\r\n<title>Panel</title>"


async def fake_open(ip, port, ssl=None):
    return Reader(), Writer()

real_open = scan_web.asyncio.open_connection
scan_web.asyncio.open_connection = fake_open
try:
    got = asyncio.run(scan_web._https_get("10.70.0.1", 443, 1.0))
finally:
    scan_web.asyncio.open_connection = real_open
assert got is not None and got[-1] == FP, got

# 2) the answer over TLS carries it; a plain answer has none
found = scan_web._describe_response(b"HTTP/1.1 200 OK\r\n\r\n<title>Panel</title>", "commonName=gw.lan", True, FP)
assert found["tls_fp"] == FP, found
assert "tls_fp" not in scan_web._describe_response(b"HTTP/1.1 200 OK\r\n\r\n<title>Panel</title>", None, False)

# 3) the port, and the web identity: the default web port, else any confirmed TLS port
port = {"port": 443, "service": "https"}
scan_web._mark_port(port, found)
assert port["tls_fp"] == FP, port
assert scan_web.web_identity([port])["tls_fp"] == FP
plain80 = {"port": 80, "service": "http"}
scan_web._mark_port(plain80, scan_web._describe_response(b"HTTP/1.1 200 OK\r\n\r\n<title>Panel</title>", None, False))
tls8443 = {"port": 8443, "service": None}
scan_web._mark_port(tls8443, {**found})
ident = scan_web.web_identity([plain80, tls8443])
assert ident["tls_fp"] == FP, ident              # 80 is the default web port (no certificate there): the one of 8443 is taken
assert "tls_fp" not in scan_web.web_identity([plain80])


# 4) the pipeline puts it into scan_info
async def fake_confirm(ip, ports):
    for p in ports:
        scan_web._mark_port(p, found if p["port"] == 443 else None)

real_confirm = pipeline_probes.scanner._confirm_http_ports
pipeline_probes.scanner._confirm_http_ports = fake_confirm
try:
    info = {"ports": [{"port": 443, "service": "https"}]}
    asyncio.run(pipeline_probes._confirm_web_identity({"http_title"}, "10.70.0.1", info))
finally:
    pipeline_probes.scanner._confirm_http_ports = real_confirm
assert info.get("tls_fp") == FP, info

# 5) kept in the saved scan, kept by a deep search while the port is still open, accepted on adding
assert scan_format.format_scan_info({**info, "mac": None, "hostname": None, "http_title": None}).get("tls_fp") == FP
assert "tls_fp" in rescan._PORT_CLUES
from app.routes import scan_routes  # noqa: E402
assert "tls_fp" in scan_routes.SCAN_INFO_KEYS
print("check_tls_fingerprint: ok")
