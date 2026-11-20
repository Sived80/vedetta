"""1.0 step P10: maclayer.successions(history, now, only, dhcp_seen) reads the last VERDICT_WINDOW_DAYS of the MAC layer (rows and sessions)
and the DHCP names, and asks macidentity.successions. A MAC the layer has not recorded yet (heard only by DHCP, or just now) counts as
started now. In-memory history, no network.
    python tests/check_maclayer_successions.py"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import maclayer  # noqa: E402
from app.maclayer import Observation  # noqa: E402
from app.storage.history import History  # noqa: E402

NOW = 1_800_000_000.0
OLD, NEW = "DA:00:00:00:00:01", "DA:00:00:00:00:02"
PHONE = {"hostname": "anna-phone", "client_id": "01:da:00:00:00:00:01", "vendor_class": "android-dhcp-14", "prl": "1,3,6,15,26"}


def seen_arp(h: History, mac: str, ip: str, start: float, end: float) -> None:
    """An ARP answer every minute from start to end: one session."""
    t = start
    while t <= end:
        h.observe([Observation(ip, mac, "arp", t)])
        t += 60


def history_with_old() -> History:
    h = History(Path(":memory:"))
    for i in range(5):                                          # other devices of the network
        seen_arp(h, "3C:00:00:00:01:%02X" % i, "192.168.1.%d" % (100 + i), NOW - 3 * 3600, NOW - 600)
    seen_arp(h, OLD, "192.168.1.20", NOW - 3 * 3600, NOW - 2 * 3600)
    return h


DHCP = {OLD.lower(): dict(PHONE), NEW.lower(): dict(PHONE)}
for i in range(5):
    DHCP["3c:00:00:00:01:%02x" % i] = {"hostname": "dev-%d" % i, "vendor_class": "linux", "prl": "1,3"}

# 1. the new MAC answered at another address after the old one stopped: a succession
h = history_with_old()
seen_arp(h, NEW, "192.168.1.31", NOW - 2 * 3600 + 120, NOW)
assert maclayer.successions(h, NOW, dhcp_seen=DHCP) == {NEW: OLD}
assert maclayer.successions(h, NOW, only={NEW}, dhcp_seen=DHCP) == {NEW: OLD}
assert maclayer.successions(h, NOW, only={"DA:00:00:00:00:99"}, dhcp_seen=DHCP) == {}

# 2. the new MAC is not in the layer yet (heard by DHCP only, this very cycle): it counts as started now, and the client id says it is the phone
h = history_with_old()
assert maclayer.successions(h, NOW, only={NEW}, dhcp_seen=DHCP) == {NEW: OLD}
# ... but a MAC nobody knows anything about (no rows, no DHCP) is not judged at all
assert maclayer.successions(h, NOW, only={NEW}, dhcp_seen={k: v for k, v in DHCP.items() if k != NEW.lower()}) == {}

# 3. the old MAC is older than the window: it is not read, no succession
h = History(Path(":memory:"))
seen_arp(h, OLD, "192.168.1.20", NOW - 9 * 86400, NOW - 9 * 86400 + 600)
seen_arp(h, NEW, "192.168.1.31", NOW - 600, NOW)
assert maclayer.successions(h, NOW, dhcp_seen=DHCP) == {}

# 4. both answering at once: two devices
h = history_with_old()
seen_arp(h, NEW, "192.168.1.31", NOW - 2.5 * 3600, NOW)
assert maclayer.successions(h, NOW, dhcp_seen=DHCP) == {}

print("check_maclayer_successions OK")
