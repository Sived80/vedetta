"""The nightly forgetting of private MACs (storage/history_known.py known_prune): a guest with a made-up MAC, gone for more than 30 days and
without a card, leaves known_macs; a MAC of a manufacturer, a MAC with a card, one ignored by the person, one seen lately or first seen
lately all stay. Seen again after being forgotten, it is a new device again (newdevices)."""
import sys
import tempfile
import time
import types
from pathlib import Path

sys.path.insert(0, ".")
try:
    import app.applog  # noqa: F401
except Exception:
    stub = types.ModuleType("app.applog")
    import logging
    stub.logger = logging.getLogger("dashboard")
    sys.modules["app.applog"] = stub

from app.storage import newdevices
from app.storage.history import History
from app.maclayer import Observation

failed = 0


def check(cond, what):
    global failed
    print(("ok   " if cond else "FAIL ") + what)
    failed += not cond


hist = History(Path(tempfile.mkdtemp()) / "t.db")
now = time.time()
old, recent = now - 40 * 86400, now - 5 * 86400

GUEST = "DA:11:22:33:44:01"      # private (second digit A), no card, gone for 40 days: forgotten
GUEST_LC = "6a:11:22:33:44:02"   # private, written in lowercase somewhere: forgotten too
VENDOR = "00:11:22:33:44:03"     # a MAC of a manufacturer, gone for 40 days: stays
CARD = "52:11:22:33:44:04"       # private but with a card (a presence event): stays
IGNORED = "F2:11:22:33:44:05"    # private, ignored by the person: stays
LATELY = "2E:11:22:33:44:06"     # private, answered ARP 5 days ago: stays
YOUNG = "AE:11:22:33:44:07"      # private, first seen 5 days ago and never again: stays (not yet 30 days)

for mac, first, status in ((GUEST, old, "known"), (GUEST_LC, old, "new"), (VENDOR, old, "known"), (CARD, old, "known"),
                           (IGNORED, old, "ignored"), (LATELY, old, "known"), (YOUNG, recent, "new")):
    hist.known_set(mac, first, "192.168.1.10", None, None, status)
hist.observe([Observation("192.168.1.10", m, "arp", old) for m in (GUEST, GUEST_LC.upper(), VENDOR, CARD, IGNORED)]
             + [Observation("192.168.1.11", LATELY, "arp", recent), Observation("192.168.1.12", YOUNG, "arp", recent)])
hist.record_presence("d1", "192.168.1.13", CARD.lower(), True, old)   # the card of CARD (its MAC in lowercase, as an older version wrote it)

check(hist.known_prune(now) == 2, "two private MACs without a card, gone for 40 days, are forgotten")
left = set(hist.known_all())
check(GUEST not in left and GUEST_LC not in left, "the guest is gone, also when the MAC was written in lowercase")
check({VENDOR, CARD, IGNORED, LATELY, YOUNG} <= left, "a manufacturer MAC, a card, an ignored one, one seen lately and one first seen lately all stay")
check(hist.known_prune(now) == 0, "a second pass forgets nothing more")

# Seen again after being forgotten: it is a new device again (it was the point of known_macs, it stays so)
hist.meta_set(newdevices.BASELINE_KEY, str(int(old)))
fresh, _ = newdevices.evaluate({GUEST: {"ip": "192.168.1.20", "hostname": None, "vendor": None}}, set(), set(), hist=hist, now=now)
check([e["mac"] for e in fresh] == [GUEST], "the guest back after being forgotten is reported as new")
fresh, _ = newdevices.evaluate({CARD: {"ip": "192.168.1.13", "hostname": None, "vendor": None}}, set(), {CARD}, hist=hist, now=now)
check(fresh == [], "a card back is not new")

print("FALLITO: %d" % failed if failed else "TUTTO OK")
sys.exit(1 if failed else 0)
