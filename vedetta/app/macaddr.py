# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""Which MACs are a device: the one rule every entry point of a MAC follows (arp-scan, the neighbour table, DHCP, the router's table by SNMP,
Home Assistant's registry, the MAC a probe reads). Standards only, no maker: IEEE 802-2014 section 8.2 (the I/G bit, the least significant bit
of the first octet, marks a group address: 01:00:5E:.. of IPv4 multicast, RFC 1112; 33:33:.. of IPv6 multicast, RFC 2464; the broadcast
FF:FF:FF:FF:FF:FF) and the all-zero MAC (no address). A unicast MAC stays, locally administered or not: VRRP's 00:00:5E:00:01:xx (RFC 5798)
is a router's, BA:BE:.. has no standard that says it is not a device. A dropped MAC is said once in the log."""
import re

from .applog import logger

_MAC = re.compile(r"^[0-9A-F]{2}([:-])[0-9A-F]{2}(\1[0-9A-F]{2}){4}$", re.IGNORECASE)
_LOGGED_MAX = 256
_logged: set[str] = set()


def is_device_mac(mac: str | None) -> bool:
    """True for a well-formed unicast MAC that is not all zeros."""
    text = str(mac or "").strip()
    if not _MAC.match(text):
        return False
    octets = bytes(int(p, 16) for p in re.split(r"[:-]", text))
    return not (octets[0] & 0x01) and any(octets)


def device_mac(mac: str | None, source: str) -> bool:
    """is_device_mac, and a log line the first time a well-formed MAC is dropped (`source`: where it came from)."""
    if is_device_mac(mac):
        return True
    text = str(mac or "").strip().upper().replace("-", ":")
    if _MAC.match(text) and text not in _logged and len(_logged) < _LOGGED_MAX:
        _logged.add(text)
        logger.info("MAC %s ignorato (%s): non è un dispositivo (multicast, broadcast o nullo)", text, source)
    return False
