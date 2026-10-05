"""Check of the DHCP parser and the mobile score (runnable locally, without network)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vedetta"))
from app import dhcp  # noqa: E402


def packet(mac: bytes, msg_type: int, hostname: str, prl: list[int], vendor: str = "") -> bytes:
    head = bytes([1, 1, 6, 0]) + b"\x00" * 24 + mac + b"\x00" * 10 + b"\x00" * 192 + dhcp._MAGIC_COOKIE
    opts = bytes([53, 1, msg_type])
    if hostname:
        opts += bytes([12, len(hostname)]) + hostname.encode()
    opts += bytes([55, len(prl)]) + bytes(prl)
    if vendor:
        opts += bytes([60, len(vendor)]) + vendor.encode()
    return head + opts + b"\xff"


android_mac = bytes.fromhex("4e3afd0000a5")  # U/L bit set
ios_mac = bytes.fromhex("be1122334455")
pc_mac = bytes.fromhex("001122334455")

cases = [
    (android_mac, "android-1a2b3c", [1, 3, 6, 15, 26, 28, 51, 58, 59, 43], "android-dhcp-14", True),
    (ios_mac, "", [1, 121, 3, 6, 15, 119, 252], "", True),
    (pc_mac, "DESKTOP-X", [1, 3, 6, 15, 31, 33, 43, 44, 46, 47, 119, 121, 249, 252], "MSFT 5.0", False),
]
for mac, host, prl, vc, expect_mobile in cases:
    parsed = dhcp.parse(packet(mac, 3, host, prl, vc))
    assert parsed, "pacchetto non letto"
    key, info = parsed
    dhcp.seen[key] = info
    score, why = dhcp.mobile_score(key, False, None)
    print(key, info.get("prl"), "->", score, why)
    assert (score >= 3) == expect_mobile, key

assert dhcp.parse(packet(pc_mac, 2, "x", [1])) is None  # server OFFER: ignored
# a private MAC alone, without other clues, is not enough
assert dhcp.mobile_score("ba:00:00:00:00:01", False, True)[0] < 3
# a name with mobile keywords is enough on its own
assert dhcp.mobile_score("00:99:99:99:99:99", True, None)[0] >= 3
# Android TV: Android fingerprint but manufacturer-assigned MAC -> not a phone
tv_mac = bytes.fromhex("38b8000000a8")
key, info = dhcp.parse(packet(tv_mac, 3, "", [1, 3, 6, 15, 26, 28, 51, 58, 59, 43], "android-dhcp-12"))
dhcp.seen[key] = info
assert dhcp.mobile_score(key, False, None)[0] < 3
# the same with a private MAC (phone): mobile
key2, info2 = dhcp.parse(packet(bytes.fromhex("4e3afd0000a6"), 3, "", [1, 3, 6, 15, 26, 28, 51, 58, 59, 43], "android-dhcp-14"))
dhcp.seen[key2] = info2
assert dhcp.mobile_score(key2, False, None)[0] >= 3
print("OK")
