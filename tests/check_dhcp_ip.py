"""The address a DHCP client says it uses (ciaddr on a renewal, option 50 on a REQUEST, never from a DISCOVER hint) and the observations made from it."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import maclayer  # noqa: E402
from app.scan import dhcp  # noqa: E402


def packet(msg_type, ciaddr=b"\x00\x00\x00\x00", requested=None, mac=bytes.fromhex("be1122334455")):
    head = bytes([1, 1, 6, 0]) + b"\x00" * 8 + ciaddr + b"\x00" * 12 + mac + b"\x00" * 10 + b"\x00" * 192 + dhcp._MAGIC_COOKIE
    opts = bytes([53, 1, msg_type]) + (bytes([50, 4]) + requested if requested else b"")
    return head + opts + b"\xff"


R = bytes([192, 168, 1, 77])
mac, info = dhcp.parse(packet(3, requested=R))
assert mac == "be:11:22:33:44:55" and info["ip"] == "192.168.1.77" and info["ip_from"] == "requested"
assert dhcp.parse(packet(3, ciaddr=bytes([192, 168, 1, 50]), requested=R))[1] == {"ip": "192.168.1.50", "ip_from": "ciaddr"}, "ciaddr wins"
assert dhcp.parse(packet(1, ciaddr=bytes([192, 168, 1, 50])))[1]["ip"] == "192.168.1.50", "a renewal-like packet with ciaddr"
assert "ip" not in dhcp.parse(packet(1, requested=R))[1], "a DISCOVER's option 50 is only a hint"
assert "ip" not in dhcp.parse(packet(3))[1], "nothing to say when the client has no address and asks for none"
assert dhcp.parse(packet(8, requested=R)) is None, "other message types are still ignored"

# the client identifier (opt 61) is read as hex and travels to the linker; a packet without it simply has none
def with_cid(cid: bytes) -> bytes:
    base = packet(3, requested=R)
    return base[:-1] + bytes([61, len(cid)]) + cid + bytes([255])


mac2, info2 = dhcp.parse(with_cid(bytes([255, 0, 0, 0, 1, 0, 1, 2, 3])))
assert info2["client_id"] == "ff000000010001020" + "3" and info2["ip"] == "192.168.1.77", info2
assert "client_id" not in dhcp.parse(packet(3, requested=R))[1]
feats = maclayer.features_for_linking([{"ip": "192.168.1.77", "mac": "BE:11:22:33:44:55", "source": "dhcp", "first_seen": 1.0, "last_seen": 2.0, "seen_count": 1}], [],
                                      {"be:11:22:33:44:55": {"hostname": "x", "client_id": "ff0000", "vendor_class": "vc", "prl": "1,3"}})
assert feats["BE:11:22:33:44:55"]["client_id"] == "ff0000" and feats["BE:11:22:33:44:55"]["fingerprint"] == "vc|1,3"

# anything that is not a client DHCP packet gives None, never an exception (this callback runs for every datagram on port 67)
for junk in (bytes([2]) * 300, bytes([1]) * 10, b"", bytes([1, 1, 6, 0]) + bytes(300), bytes([2]) + packet(3)[1:]):
    assert dhcp.parse(junk) is None, junk[:6]
assert dhcp.parse(packet(2)) is None, "a DHCPOFFER from a server is not a client request"

# the address is only as recent as the packet that carried it: a DISCOVER later keeps the old address but must not make it look new
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402
dhcp.STORE_PATH = Path(tempfile.mkdtemp()) / "dhcp_seen.json"
dhcp.seen.clear()
clock = {"t": 1000.0}
real_time = dhcp.time.time
dhcp.time.time = lambda: clock["t"]
saves = []
real_save = dhcp._save
dhcp._save = lambda: saves.append(1)
lis = dhcp._Listener()
lis.datagram_received(packet(3, requested=R), None)
e = dhcp.seen["be:11:22:33:44:55"]
assert e["ip"] == "192.168.1.77" and e["ip_ts"] == 1000 and e["seen"] == 1000
clock["t"] = 1100.0
lis.datagram_received(packet(1), None)                    # DISCOVER: no address
e = dhcp.seen["be:11:22:33:44:55"]
assert e["ip"] == "192.168.1.77" and e["ip_ts"] == 1000 and e["seen"] == 1100, e
obs_now = maclayer.from_dhcp(dhcp.seen, 5000.0)
assert [o.ts for o in obs_now] == [1000.0], "the observation carries the age of the address, not of the last packet"
clock["t"] = 1200.0
n = len(saves)
lis.datagram_received(packet(3, requested=R), None)       # the same request again: a renewal, nothing changed -> no new save, but the address is renewed
assert len(saves) == n and dhcp.seen["be:11:22:33:44:55"]["ip_ts"] == 1200
dhcp.time.time, dhcp._save = real_time, real_save
legacy = maclayer.from_dhcp({"be:11:22:33:44:55": {"ip": "192.168.1.77", "seen": 77}}, 5000.0)
assert [o.ts for o in legacy] == [77.0], "an entry written before ip_ts existed falls back to seen"

obs = maclayer.from_dhcp({"be:11:22:33:44:55": {"ip": "192.168.1.77", "seen": 50}, "aa:aa:aa:00:00:01": {"hostname": "x", "seen": 5}, "bad": {"ip": "1.1.1.1"}}, 100.0)
assert obs == [maclayer.Observation("192.168.1.77", "BE:11:22:33:44:55", "dhcp", 50.0)], obs
print("TUTTO OK")
