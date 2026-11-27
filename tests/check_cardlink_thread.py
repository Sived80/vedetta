# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The judgement of the card links runs in a thread (cardlink_cycle.update, 18/11): what it took is forgotten when it is done, but a request
made while it ran (the person pressed «This is a new device» meanwhile) stays for the next judgement (18/11 review: it was lost)."""
import asyncio
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import cardlink_cycle, linkview, netutil  # noqa: E402

netutil.last_network = "192.168.1.0/24"
linkview.release("a")                  # taken by the judgement
linkview.release("b")                  # taken, and nothing else happens to it


def judge(history, now, requests):
    assert requests == {"a": ("release", None), "b": ("release", None)}, requests
    linkview.relink("a", "AA:00:00:00:00:02")        # the gesture, while the thread runs
    return ({}, now), {"offers": {}, "done": ["a", "b"]}, {"seen": 2, "moved": 1, "unlinked": ["held"], "two_private": 3}


cardlink_cycle._judge_and_store = judge
cardlink_cycle._last = 0.0
asyncio.run(cardlink_cycle.update(object(), now=10_000.0))
assert linkview.requests() == {"a": ("relink", "AA:00:00:00:00:02")}, linkview.requests()
assert linkview.check("a", 1, "main", 10_001.0)[1] in ("released", "none")
# the counts of the export are set on the loop, from what the thread returned (18/11 review 3: the thread changed them while an export read them)
assert cardlink_cycle._succession["seen"] == 2 and cardlink_cycle._two_private == 3 and dict(cardlink_cycle._unlinked) == {"held": 1}
print("ALL OK")
