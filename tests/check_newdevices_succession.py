# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""1.0 step P10 (decision 1A): a private MAC never seen before that is the successor of a known one (maclayer.successions) inherits the state
of the old MAC and is never alerted: the phone of every day that rotated its MAC is not a new device. The successions are asked once per
round and only when there are MACs never seen before (`predecessor` callback); a callback that fails changes nothing.
    python tests/check_newdevices_succession.py"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.storage import newdevices  # noqa: E402
from app.storage.history import History  # noqa: E402

OLD, NEW, OTHER, TV = "DA:00:00:00:00:01", "DA:00:00:00:00:02", "DA:00:00:00:00:03", "3C:00:00:00:00:50"


def obs(*pairs) -> dict:
    return {mac: {"ip": ip, "vendor": None, "hostname": None} for ip, mac in pairs}


def fresh_hist() -> History:
    h = History(Path(tempfile.mkdtemp()) / "t.db")
    newdevices.evaluate(obs(("192.168.1.20", OLD), ("192.168.1.50", TV)), set(), set(), hist=h)     # the starting point: both known
    return h


calls = []


def preds(table):
    def ask(macs):
        calls.append(set(macs))
        return {m: table[m] for m in macs if m in table}
    return ask


# 1. the known phone rotates: the new MAC is known, no alert, not in the list of the new ones
h = fresh_hist()
fresh, current = newdevices.evaluate(obs(("192.168.1.31", NEW), ("192.168.1.50", TV)), set(), set(), hist=h, predecessor=preds({NEW: OLD}))
assert fresh == [] and current == [], (fresh, current)
assert h.known_all()[NEW]["status"] == "known"
assert calls == [{NEW}], calls

# 2. a MAC with no predecessor is still a new device, as before
calls.clear()
fresh, _ = newdevices.evaluate(obs(("192.168.1.32", OTHER)), set(), set(), hist=h, predecessor=preds({NEW: OLD}))
assert [f["mac"] for f in fresh] == [OTHER] and calls == [{OTHER}]

# 3. no MAC never seen before: the callback is not even asked (it reads the history: not every cycle for nothing)
calls.clear()
newdevices.evaluate(obs(("192.168.1.31", NEW), ("192.168.1.50", TV)), set(), set(), hist=h, predecessor=preds({}))
assert calls == []

# 4. the old MAC was itself a new device (never added): the successor stays new, in the list, but is not alerted a second time
h = History(Path(tempfile.mkdtemp()) / "t.db")
newdevices.evaluate(obs(("192.168.1.50", TV)), set(), set(), hist=h)
first, _ = newdevices.evaluate(obs(("192.168.1.50", TV), ("192.168.1.20", OLD)), set(), set(), hist=h)
assert [f["mac"] for f in first] == [OLD]
fresh, current = newdevices.evaluate(obs(("192.168.1.50", TV), ("192.168.1.31", NEW)), set(), set(), hist=h, predecessor=preds({NEW: OLD}))
assert fresh == [] and NEW in [c["mac"] for c in current] and h.known_all()[NEW]["status"] == "new"

# 5. the old MAC was configured (a card is linked to it): the successor is known
h = fresh_hist()
newdevices.evaluate(obs(("192.168.1.50", TV)), set(), {OLD}, hist=h)
fresh, _ = newdevices.evaluate(obs(("192.168.1.31", NEW)), set(), {OLD}, hist=h, predecessor=preds({NEW: OLD}))
assert fresh == [] and h.known_all()[NEW]["status"] == "known"

# 6. a predecessor the table does not know (outside the history): nothing to inherit, a new device as before
h = fresh_hist()
fresh, _ = newdevices.evaluate(obs(("192.168.1.31", NEW)), set(), set(), hist=h, predecessor=preds({NEW: "DA:00:00:00:00:77"}))
assert [f["mac"] for f in fresh] == [NEW]


# 7. a callback that fails: as if there were no successions (the alerts never depend on it)
def broken(macs):
    raise RuntimeError("history unreadable")


h = fresh_hist()
fresh, _ = newdevices.evaluate(obs(("192.168.1.31", NEW)), set(), set(), hist=h, predecessor=broken)
assert [f["mac"] for f in fresh] == [NEW]

print("check_newdevices_succession OK")
