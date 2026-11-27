# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The survey of the host's interfaces (networks/host_read.py) runs at every answer of the Networks panel, and since 1.0.1 the tiles ask for
it once a minute: an interface without an IPv4 address (a container's veth, a bridge not in use) is normal and must not write a line in
the log every time ("network survey: no IPv4 for vethc6cd6c3 ([Errno 99] Address not available)", seen on the debug copy, 20/11).
Another error is still written. A fake fcntl module stands in for the kernel: no real interface is read.
    python tests/check_host_read_quiet.py"""
import errno
import logging
import os
import sys
import tempfile
import types

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.applog import logger  # noqa: E402
from app.networks import host_read  # noqa: E402

lines = []


class Grab(logging.Handler):
    def emit(self, record):
        lines.append(record.getMessage())


logger.addHandler(Grab())
logger.setLevel(logging.DEBUG)
failed = 0


def check(cond, msg):
    global failed
    print(("ok: " if cond else "FAILED: ") + msg)
    failed += 0 if cond else 1


def fake_fcntl(code):
    mod = types.ModuleType("fcntl")

    def ioctl(*args):
        raise OSError(code, os.strerror(code))
    mod.ioctl = ioctl
    return mod


sys.modules["fcntl"] = fake_fcntl(errno.EADDRNOTAVAIL)
check(host_read._ipv4_addresses("vethc6cd6c3") == [], "an interface without IPv4: no address")
check(not lines, "and no line in the log: " + repr(lines))
sys.modules["fcntl"] = fake_fcntl(errno.ENODEV)
check(host_read._ipv4_addresses("gone0") == [], "another error: no address either")
check(any("gone0" in line for line in lines), "but it is written in the log: " + repr(lines))
print("ALL OK" if not failed else f"{failed} FAILED")
sys.exit(1 if failed else 0)
