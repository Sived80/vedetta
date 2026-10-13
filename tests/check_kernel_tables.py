"""Behaviour of the three readers of the tables the kernel exposes: the default gateway (/proc/net/route), the ARP table (/proc/net/arp) and the memory and threads of the process (/proc/self/status).
Written on the code BEFORE the shared reader was made and kept passing after it: the differential proof that the refactoring did not change what they answer (a missing file, a short line, a bad number,
a byte that is not ASCII)."""
import builtins
import os
import sys
import tempfile
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import state_support  # noqa: E402
from app.recognition import identity  # noqa: E402
from app.scan import latency  # noqa: E402

tmp = Path(tempfile.mkdtemp())


def write(name: str, data: bytes) -> str:
    path = tmp / name
    path.write_bytes(data)
    return str(path)


HEAD = b"Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\tMTU\tWindow\tIRTT\n"
ROUTE = "eth0\t{dest}\t{gw}\t{flags}\t0\t0\t100\t00000000\t0\t0\t0\n"


def route(*rows) -> bytes:
    return HEAD + "".join(ROUTE.format(dest=d, gw=g, flags=f) for d, g, f in rows).encode()


# --- the default gateway
read = identity._read_gateway
assert read(write("r1", route(("0000A8C0", "00000000", "0001"), ("00000000", "0101A8C0", "0003")))) == "192.168.1.1", "the first default route, the others are skipped"
assert read(write("r2", route(("00000000", "0101A8C0", "0001")))) is None, "a default route without the gateway flag is no gateway"
assert read(write("r3", route(("00000000", "0101A8C0", "0003"), ("00000000", "0202A8C0", "0003")))) == "192.168.1.1", "the first of two"
assert read(write("r4", route(("0000A8C0", "00000000", "0001")))) is None
assert read(write("r5", b"")) is None and read(write("r6", HEAD)) is None
assert read(str(tmp / "missing")) is None
assert read(write("r7", route(("00000000", "0101A8C0", "zz")))) is None, "a bad number in the flags ends the reading with no answer"
assert read(write("r8", HEAD + b"short line\n" + route(("00000000", "0101A8C0", "0003"))[len(HEAD):])) == "192.168.1.1", "a short line is skipped"
assert read(write("r9", route(("00000000", "0101A8C0", "0003")) + b"\xff\xfe\n")) is None, "a byte that is not ASCII: no answer"

# --- the ARP table
ARP_HEAD = b"IP address       HW type     Flags       HW address            Mask     Device\n"
arp = latency.arp_known
table = write("a1", ARP_HEAD + b"192.168.1.5     0x1         0x2         aa:bb:cc:dd:ee:01     *        eth0\n192.168.1.6     0x1         0x0         00:00:00:00:00:00     *        eth0\n")
assert arp("192.168.1.5", table) is True, "complete entry"
assert arp("192.168.1.6", table) is False, "incomplete entry (flags 0x0)"
assert arp("192.168.1.7", table) is False and arp("IP", table) is False, "unknown address, and the header is skipped"
assert arp("192.168.1.5", str(tmp / "missing")) is False
assert arp("192.168.1.5", write("a2", ARP_HEAD + b"192.168.1.5 0x1\n")) is False, "a short line"
assert arp("192.168.1.5", write("a3", b"\xff\n" + ARP_HEAD + b"192.168.1.5 0x1 0x2 aa:bb:cc:dd:ee:01 * eth0\n")) is True, "bytes that are not ASCII are ignored here"
assert arp("192.168.1.5", write("a4", b"")) is False

# --- the process: the fixed path /proc/self/status is redirected to a fixture (the function is called as the service calls it)
real_open = builtins.open
current = {"path": None}


def redirected(file, *args, **kwargs):
    return real_open(current["path"] if file == "/proc/self/status" else file, *args, **kwargs)


def process(data: bytes | None) -> dict:
    current["path"] = write("status", data) if data is not None else str(tmp / "missing-status")
    builtins.open = redirected
    try:
        return state_support._process_info()
    finally:
        builtins.open = real_open


assert process(b"Name:\tpython\nVmRSS:\t  12345 kB\nThreads:\t7\n") == {"rss_mb": 12, "threads": 7}
assert process(b"Name:\tpython\n") == {}
assert process(None) == {}, "no file (not Linux): nothing"
assert process(b"Threads:\t7\nVmRSS:\tabc kB\n") == {"threads": 7}, "a bad number ends the reading and keeps what was read"
assert process(b"VmRSS:\t2048 kB\n\xff\n") == {}, "a byte that is not ASCII: the reading ends with nothing"
print("TUTTO OK")
