# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The Bonjour memory is bounded: a flood of announcements from invented addresses keeps at most CARDS_MAX cards by MAC and by IP (the
oldest go first), a card by MAC not heard for MAC_TTL_S is forgotten like the ones by IP, and the per-IP meta of the scan has a cap too.
No socket is opened: the ARP table and the verdict are fakes."""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import mdns_listener, scan_mdns  # noqa: E402

mdns_listener.STORE_PATH = Path(tempfile.mkdtemp()) / "mdns_seen.json"
mdns_listener._is_lent_mac = lambda mac: False
CAP = getattr(mdns_listener, "CARDS_MAX", 2000)
META_CAP = getattr(scan_mdns, "META_MAX", 2000)
N = CAP + 300


def ip_of(n: int) -> str:
    return f"10.70.{n >> 8}.{n & 0xFF}"


def mac_of(n: int) -> str:
    return f"02:70:00:00:{n >> 8:02x}:{n & 0xFF:02x}"


arp = {ip_of(n): mac_of(n) for n in range(N)}
mdns_listener._mac_for_ip = arp.get
t0 = time.time()
for n in range(N):
    mdns_listener.record(ip_of(n), "_http._tcp", f"dev-{n}", "", now=t0 - N + n)
assert len(mdns_listener.by_mac) <= CAP, len(mdns_listener.by_mac)
assert mac_of(0) not in mdns_listener.by_mac and mac_of(N - 1) in mdns_listener.by_mac, "the oldest card must go first"

# by IP (MAC still unknown) the same cap
mdns_listener._mac_for_ip = lambda ip: None
for n in range(N):
    mdns_listener.record(ip_of(n), "_http._tcp", f"dev-{n}", "", now=t0 - N + n)
assert len(mdns_listener.by_ip) <= CAP, len(mdns_listener.by_ip)
assert ip_of(0) not in mdns_listener.by_ip and ip_of(N - 1) in mdns_listener.by_ip

# a card by MAC not heard for longer than the TTL is forgotten at the housekeeping, a recent one stays
mdns_listener.by_ip.clear()
mdns_listener.by_mac.clear()
ttl = getattr(mdns_listener, "MAC_TTL_S", 90 * 86400)
mdns_listener.by_mac["02:70:00:00:aa:01"] = {"name": "old", "seen": time.time() - ttl - 3600}
mdns_listener.by_mac["02:70:00:00:aa:02"] = {"name": "recent", "seen": time.time() - 3600}
mdns_listener._housekeeping()
assert "02:70:00:00:aa:01" not in mdns_listener.by_mac and "02:70:00:00:aa:02" in mdns_listener.by_mac, mdns_listener.by_mac

# the meta collected by the scans, per IP
for n in range(N):
    scan_mdns._store_meta({ip_of(n): {"model": f"m{n}", "services": {"_http._tcp"}}})
assert len(scan_mdns.mdns_meta) <= META_CAP, len(scan_mdns.mdns_meta)
assert ip_of(0) not in scan_mdns.mdns_meta and scan_mdns.mdns_meta[ip_of(N - 1)]["model"] == f"m{N - 1}"
scan_mdns._store_meta({ip_of(N - 1): {"manufacturer": "x"}})
assert scan_mdns.mdns_meta[ip_of(N - 1)] == {"model": f"m{N - 1}", "services": ["_http._tcp"], "manufacturer": "x"}
print("OK")
