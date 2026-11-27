# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""1.0 step P10 (decision 1A): when the MAC a card is linked to rotates (maclayer.successions: {new: old}), the link passes to the new MAC,
source "identity", through the one writer of card_mac (cardlink_cycle). cardlink.successors is pure: refused when the card is gone or has
another seq, or when the new MAC is already another card's link on that network. An exception to decision 4A ("a link is never moved"): the
judge of identity says it is the same device, not another one.
    python tests/check_cardlink_successors.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import cardlink  # noqa: E402

NOW = 1_800_000_000.0
OLD, NEW = "DA:00:00:00:00:01", "DA:00:00:00:00:02"
NET = "192.168.1.0/24"


def row(device_id, mac, seq=1, state="linked", reason=None, source="rule"):
    return {"device_id": device_id, "seq": seq, "network": NET, "mac": mac, "state": state, "reason": reason, "source": source,
            "ip": "192.168.1.20", "since": NOW - 86400, "changed": NOW - 86400}


def card(device_id, seq=1, ip="192.168.1.20"):
    return {"id": device_id, "seq": seq, "ip": ip, "network": NET, "name": "Telefono di Anna", "name_mac": None}


# 1. the phone's MAC rotated: the link passes to the new MAC, source "identity", linked, the old row replaced (delete then write)
out = cardlink.successors({"phone": row("phone", OLD)}, {NEW: OLD}, [card("phone")], NOW)
moved = out["links"]["phone"]
assert (moved["mac"], moved["source"], moved["state"], moved["reason"], moved["changed"]) == (NEW, "identity", "linked", None, NOW), moved
assert out["write"] == [moved] and out["delete"] == ["phone"] and out["moved"] == 1
# a held link moves too (held while the old MAC named no single device): the judge decides again on the new MAC
out = cardlink.successors({"phone": row("phone", OLD, state="held", reason="conflict")}, {NEW: OLD}, [card("phone")], NOW)
assert out["links"]["phone"]["mac"] == NEW and out["links"]["phone"]["state"] == "linked"

# 2. nothing to move: no succession, or a succession of a MAC no card is linked to
links = {"phone": row("phone", OLD)}
for succ in ({}, {NEW: "DA:00:00:00:00:77"}):
    out = cardlink.successors(links, succ, [card("phone")], NOW)
    assert out == {"links": links, "write": [], "delete": [], "moved": 0}, out

# 3. refused: the card is gone, or it has another seq (the id belongs to another card now)
for cards in ([], [card("phone", seq=2)]):
    out = cardlink.successors({"phone": row("phone", OLD)}, {NEW: OLD}, cards, NOW)
    assert out["write"] == [] and out["links"]["phone"]["mac"] == OLD

# 4. refused: the new MAC is already the link of another card on that network
links = {"phone": row("phone", OLD), "tablet": row("tablet", NEW)}
out = cardlink.successors(links, {NEW: OLD}, [card("phone"), card("tablet", ip="192.168.1.21")], NOW)
assert out["write"] == [] and out["links"] == links

# 5. the keys are compared in one form (upper case, colons)
out = cardlink.successors({"phone": row("phone", OLD)}, {NEW.lower().replace(":", "-"): OLD.lower()}, [card("phone")], NOW)
assert out["links"]["phone"]["mac"] == NEW

print("check_cardlink_successors OK")
