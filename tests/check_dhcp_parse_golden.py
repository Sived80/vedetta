"""Golden-master test of dhcp.parse (a client packet -> MAC and options) and dhcp._os_family (the family of the system from the options it asks for and its vendor
class): 2500 generated packets (valid ones with every option, repeated and out of order, padding, a missing end, lengths that run past the packet, truncated,
wrong op or cookie, a server reply) and 1500 generated fingerprints (every family rule, near misses, odd values) must give exactly the output stored in
tests/golden/dhcp_parse.json, written from the code as it was before the functions were split.
Regenerate only on purpose:  DHCP_GOLDEN_UPDATE=1 python tests/check_dhcp_parse_golden.py"""
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import dhcp  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "dhcp_parse.json"
N_PACKETS, N_PRINTS = 2500, 1500
rng = random.Random(6767)


def pick(seq):
    return seq[rng.randrange(len(seq))]


def option(code: int) -> bytes:
    if code == 53:
        return bytes([53, 1, pick([1, 2, 3, 4, 5, 6, 7, 8, 0, 255])])
    if code in (12, 60):
        s = pick([b"giulia-ipad", b"android-dhcp-13", b"MSFT 5.0", b"  padded \x00", b"\xff\xfe bad utf", b"", b"x" * 60])
        return bytes([code, len(s)]) + s
    if code == 55:
        lst = bytes(rng.sample([1, 3, 6, 15, 26, 28, 33, 44, 46, 51, 58, 59, 95, 119, 121, 249, 252], rng.randrange(0, 9)))
        return bytes([55, len(lst)]) + lst
    if code == 61:
        s = pick([b"", b"\x01\xaa\xbb\xcc\xdd\xee\xff", b"\xff\x00\x00\x00\x01\x00\x01\x00\x01\xaa"])
        return bytes([61, len(s)]) + s
    if code in (54, 50):
        s = pick([bytes([192, 168, 1, rng.randrange(1, 250)]), bytes([10, 0, 0]), b""])
        return bytes([code, len(s)]) + s
    return bytes([code, 2, 9, 9])


def packet() -> bytes:
    op = pick([1] * 9 + [2])
    head = bytearray(240)
    head[0] = op
    head[12:16] = pick([bytes(4), bytes([192, 168, 1, 77]), bytes(4)])       # ciaddr
    head[28:34] = bytes(rng.randrange(256) for _ in range(6))
    head[236:240] = pick([b"\x63\x82\x53\x63"] * 6 + [b"\x00\x00\x00\x00"])
    opts = bytes([53, 1, pick([1, 3, 3, 1, 8, 2, 5])]) if rng.random() < 0.8 else b""      # most clients start with their message type
    for _ in range(rng.randrange(0, 9)):
        r = rng.random()
        opts += bytes([0]) * rng.randrange(0, 3) if r < 0.1 else option(pick([53, 53, 12, 55, 60, 61, 54, 50, 50, 77, 255]))
    tail = pick([b"\xff", b"\xff", b"", b"\xff\x00\x00", bytes([12, 200]) + b"abc"])      # the last one: a length that runs past the packet
    data = bytes(head) + opts + tail
    if rng.random() < 0.06:
        data = data[: rng.randrange(0, len(data))]
    return data


def parse(data: bytes):
    try:
        res = dhcp.parse(data)
    except Exception as exc:
        return {"exception": type(exc).__name__}
    return None if res is None else [res[0], res[1]]


VENDORS = [None, "", "ChromeOS", "chrome os 14", "android-dhcp-13", "Android-DHCP-9", "MSFT 5.0", "msft", "dhcpcd-9.4", "udhcp 1.31", "dhcpcd", "iPhone", "xmsft", " msft"]


def fingerprint():
    if rng.random() < 0.2:
        prl = pick([None, "", "x", "1,,3", "a,b"])
    else:
        base = pick([[1, 121, 3, 6, 15, 119, 252], [1, 121, 3, 6, 15, 119, 252, 95, 44, 46], [1, 121, 3, 252], [1, 3, 6, 15, 31, 33, 43, 44, 46, 47, 119, 121, 249, 252],
                     [1, 3, 6, 15, 26, 28, 51, 58, 59, 43], [1, 28, 2, 3, 15, 6, 12], [1, 3, 6], [121, 1, 3, 252], [1, 121, 3]])
        opts = list(base)
        if rng.random() < 0.5:
            rng.shuffle(opts)
        if rng.random() < 0.3:
            opts = opts[: rng.randrange(0, len(opts) + 1)]
        if rng.random() < 0.3:
            opts += rng.sample([95, 44, 249, 252, 26, 28, 51, 58, 12, 7], rng.randrange(1, 4))
        prl = ",".join(str(o) for o in opts)
    return prl, pick(VENDORS)


FIXED = [("1,121,3,252,44", None), ("1,121,3,252,95", None), ("1,121,3,252,46", None), ("1,121,3,252", None), ("1,121,3,252,44,95", None), ("1,121,3,6,15,119,252,44", "")]
N_PRINTS += len(FIXED)         # the edges of the iOS / macOS rule, written by hand
out = {"parse": [parse(packet()) for _ in range(N_PACKETS)], "family": [[*fp, dhcp._os_family(*fp)] for fp in FIXED + [fingerprint() for _ in range(N_PRINTS - len(FIXED))]]}
out = json.loads(json.dumps(out, sort_keys=True, default=str))
if os.environ.get("DHCP_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(out, sort_keys=True, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want["parse"]) == len(out["parse"]) == N_PACKETS and len(want["family"]) == len(out["family"]) == N_PRINTS
for i, (x, y) in enumerate(zip(out["parse"], want["parse"])):
    assert x == y, "packet %d differs: %s" % (i, json.dumps([x, y])[:400])
for i, (x, y) in enumerate(zip(out["family"], want["family"])):
    assert x == y, "fingerprint %d differs: %s" % (i, json.dumps([x, y])[:400])
parsed = [r for r in out["parse"] if isinstance(r, list)]
assert len(parsed) > 400 and sum(1 for r in out["parse"] if r is None) > 400 and not any(isinstance(r, dict) for r in out["parse"]), "packets too uniform"
assert any("ip_from" in r[1] and r[1]["ip_from"] == "ciaddr" for r in parsed) and any(r[1].get("ip_from") == "requested" for r in parsed) and any("client_id" in r[1] for r in parsed)
assert any("server_id" in r[1] for r in parsed) and any("prl" in r[1] for r in parsed) and any("vendor_class" in r[1] for r in parsed)
fams = {r[2] for r in out["family"]}
assert {"ios", "macos", "windows", "android", "linux", "chromeos", None} <= fams, fams
print("TUTTO OK")
