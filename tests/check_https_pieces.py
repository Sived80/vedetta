# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""A page over TLS sent in pieces (headers in one record, the page in the next ones: many small servers do it) is read whole, like the
plain one (scan_web._read_rest), and still within 64 KiB. No socket: the TLS connection is a fake."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import scan_web  # noqa: E402


class Writer:
    def get_extra_info(self, name):
        return None

    def write(self, data):
        pass

    async def drain(self):
        pass

    def close(self):
        pass

    async def wait_closed(self):
        pass


class Reader:
    def __init__(self, pieces):
        self.pieces = list(pieces)

    async def read(self, n):
        return self.pieces.pop(0)[:n] if self.pieces else b""


def fetch(pieces):
    async def fake_open(ip, port, ssl=None):
        return Reader(pieces), Writer()
    real = scan_web.asyncio.open_connection
    scan_web.asyncio.open_connection = fake_open
    try:
        return asyncio.run(scan_web._https_get("10.70.0.1", 443, 1.0))
    finally:
        scan_web.asyncio.open_connection = real


got = fetch([b"HTTP/1.1 200 OK\r\nServer: test\r\n\r\n", b"<html><head>", b"<title>Panel</title></head></html>"])
assert got is not None and b"<title>Panel</title>" in got[0], got
assert scan_web._describe_response(got[0], None, True)["title"] == "Panel"
big = fetch([b"HTTP/1.1 200 OK\r\n\r\n"] + [b"x" * 30000] * 10)
assert big is not None and len(big[0]) <= 65536, len(big[0])
print("ALL OK")
