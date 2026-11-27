# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The passive DHCP memory is bounded: a flood of invented MACs (a hostile or broken client on the segment) keeps at most SEEN_MAX cards and
SERVERS_MAX servers, the oldest go first, and the file is not rewritten at every packet: one save, later, off the packet path. No socket is opened."""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import dhcp  # noqa: E402

dhcp.STORE_PATH = Path(tempfile.mkdtemp()) / "dhcp_seen.json"
SEEN_MAX = getattr(dhcp, "SEEN_MAX", 2000)
SERVERS_MAX = getattr(dhcp, "SERVERS_MAX", 64)


def packet(n: int) -> bytes:
    mac = bytes([0x02, 0x70, 0, (n >> 16) & 0xFF, (n >> 8) & 0xFF, n & 0xFF])
    head = bytes([1, 1, 6, 0]) + b"\x00" * 24 + mac + b"\x00" * 10 + b"\x00" * 192 + dhcp._MAGIC_COOKIE
    host = f"host-{n}".encode()
    server = bytes([10, 70, (n >> 8) & 0xFF, n & 0xFF])
    return head + bytes([53, 1, 3, 12, len(host)]) + host + bytes([54, 4]) + server + b"\xff"


saves = []
real_save = dhcp._save
dhcp._save = lambda *a: saves.append(1) or real_save(*a)


async def flood() -> None:
    listener = dhcp._Listener()
    clock = [1000.0]
    dhcp.time.time = lambda: clock[0]
    for n in range(SEEN_MAX + 300):
        clock[0] += 1
        listener.datagram_received(packet(n), ("10.70.0.1", 68))
    assert len(saves) == 0, f"saved {len(saves)} times on the packet path"
    assert len(dhcp.seen) <= SEEN_MAX, len(dhcp.seen)
    assert len(dhcp.servers) <= SERVERS_MAX, len(dhcp.servers)
    assert "02:70:00:00:00:00" not in dhcp.seen, "the oldest card must go first"
    last = SEEN_MAX + 299
    assert f"02:70:00:{(last >> 16) & 0xFF:02x}:{(last >> 8) & 0xFF:02x}:{last & 0xFF:02x}" in dhcp.seen
    await dhcp.flush()                 # what the tick or the shutdown does
    assert len(saves) == 1, saves
    stored = json.loads(dhcp.STORE_PATH.read_text(encoding="utf-8"))
    assert len(stored) == len(dhcp.seen)
    assert not [p for p in dhcp.STORE_PATH.parent.iterdir() if p.suffix == ".tmp"]


asyncio.run(flood())

# at shutdown what is still unsaved is written (the listener is closed first)
dhcp.seen["02:70:09:00:00:01"] = {"seen": 5, "hostname": "late"}
dhcp._dirty = True
closed = []
dhcp.stop(type("T", (), {"close": lambda self: closed.append(1)})())
assert closed and "02:70:09:00:00:01" in json.loads(dhcp.STORE_PATH.read_text(encoding="utf-8"))

# a file written by an older version with more cards than the cap is trimmed when it is read back
dhcp.seen.clear()
dhcp.STORE_PATH.write_text(json.dumps({f"02:70:01:00:{n >> 8:02x}:{n & 0xFF:02x}": {"seen": n} for n in range(SEEN_MAX + 10)}), encoding="utf-8")
dhcp._load()
assert len(dhcp.seen) <= SEEN_MAX and "02:70:01:00:00:00" not in dhcp.seen
print("OK")
