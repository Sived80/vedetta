"""The card -> MAC links as the cycle reads them (1.0 step P5, linkview): a stored link is used only when it may be trusted now. One case per
condition (U1-U6 of the plan): the row is "linked" (U1), its seq is the card's (U2), its network is the card's network now (U3), it has been
stable for two judgements (U4, decision A of 12/11: the case S10, a repeater linked to its own MAC just before it starts lending it), a judgement
of this run came after it was made or changed (U5), and the verdict of this cycle does not call its MAC lent, virtual, on two addresses or in a
conflict (U6). Then: a link released (two cards of one phone merged) is not used again until the one writer deleted it; the requests reach the
writer and are forgotten only once it wrote them; the offers of the gesture "this is a new device" are kept per card."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import linkview, macverdict  # noqa: E402

NOW = 1_800_000_000.0
M1, M2 = "02:00:00:00:01:01", "02:00:00:00:01:02"


def row(device_id="c1", mac=M1, seq=1, network="main", state="linked", changed=NOW - 3600, reason=None):
    return {"device_id": device_id, "seq": seq, "network": network, "mac": mac, "state": state, "reason": reason, "source": "rule",
            "ip": "10.0.40.11", "since": changed, "changed": changed}


def check(device_id="c1", seq=1, network="main", now=NOW):
    return linkview.check(device_id, seq, network, now)


# nothing is known before the first reading
assert check() == (None, "none"), check()
assert linkview.JUDGE_S == 300.0 and linkview.STABLE_S == 600.0      # two judgements of cardlink_cycle (arpview.FULL_SWEEP_S)

# at start the stored rows are read, but no judgement of this run has seen them yet (U5)
linkview.load({"c1": row()})
assert check() == (None, "unjudged"), check()
# the first judgement of this run, after the link was made: usable
linkview.refresh({"c1": row()}, judged_at=NOW - 60)
assert check() == (M1, "used"), check()
macverdict.refresh({M1: "normal"})
assert check() == (M1, "used"), check()

# U1: a held link is not used
linkview.refresh({"c1": row(state="held", reason="lender")}, judged_at=NOW - 60)
assert check() == (None, "held"), check()
# U2: another seq (the card was removed and added again with the same id)
linkview.refresh({"c1": row(seq=2)}, judged_at=NOW - 60)
assert check() == (None, "seq"), check()
# U3: the card is on another network now (or on none: an address that is not on the line of a direct network)
linkview.refresh({"c1": row()}, judged_at=NOW - 60)
assert check(network="lab") == (None, "network"), check(network="lab")
assert check(network=None) == (None, "network")
# U4: born 9 minutes ago, judged again since: not yet; 11 minutes ago and judged again: used
linkview.refresh({"c1": row(changed=NOW - 540)}, judged_at=NOW - 200)
assert check() == (None, "young"), check()
linkview.refresh({"c1": row(changed=NOW - 660)}, judged_at=NOW - 60)
assert check() == (M1, "used"), check()
# U5: old enough, but no judgement of this run came JUDGE_S after it changed (a judgement that failed is only logged)
linkview.refresh({"c1": row(changed=NOW - 700)}, judged_at=NOW - 700 + 299)
assert check() == (None, "unjudged"), check()
linkview.refresh({"c1": row(changed=NOW - 700)}, judged_at=NOW - 700 + 300)
assert check() == (M1, "used"), check()
# U6: the verdict of THIS cycle calls M lent, virtual, on two addresses or in a conflict: not used, before any judgement holds the row
for kind in ("lender", "virtual", "multi_address", "conflict"):
    macverdict.refresh({M1: kind})
    assert check() == (None, "kind"), (kind, check())
for kind in ("normal", "private"):
    macverdict.refresh({M1: kind})
    assert check() == (M1, "used"), (kind, check())
macverdict.refresh({})
assert check() == (M1, "used"), "a MAC without verdict (not seen in the window): the link stands"
# a card without a row
assert check("c9") == (None, "none")

# the rows of the judgement replace the last ones in one step
linkview.refresh({"c2": row("c2", M2)}, judged_at=NOW - 60)
assert check() == (None, "none") and check("c2") == (M2, "used")
assert linkview.row("c2")["mac"] == M2 and linkview.row("c1") is None

# release (two cards of one phone merged): not used from now, and asked of the one writer; the request stays until the writer wrote it
linkview.release("c2")
assert check("c2") == (None, "released"), check("c2")
assert linkview.requests() == {"c2": ("release", None)}, linkview.requests()
linkview.refresh({"c2": row("c2", M2)}, judged_at=NOW - 30)              # a judgement that did not take the request (it failed before)
assert check("c2") == (None, "released") and linkview.requests() == {"c2": ("release", None)}
linkview.refresh({}, judged_at=NOW - 20, done=["c2"])                   # the writer deleted the row
assert check("c2") == (None, "none") and linkview.requests() == {}
linkview.refresh({"c2": row("c2", M2, changed=NOW - 10)}, judged_at=NOW - 10)    # linked again by the rule: a new link waits as any other
assert check("c2") == (None, "young")

# relink (the gesture): a request with the new MAC; the old link is not used meanwhile
linkview.refresh({"c1": row()}, judged_at=NOW - 60, offers={"c1": M2})
assert linkview.offer("c1") == M2 and linkview.offer("c2") is None
linkview.relink("c1", M2)
assert linkview.requests() == {"c1": ("relink", M2)} and check() == (None, "released")
linkview.refresh({"c1": row(mac=M2, changed=NOW)}, judged_at=NOW, done=["c1"])
assert linkview.requests() == {} and check() == (None, "young") and linkview.offer("c1") is None

# the counts of presence by MAC since the start (the export): only numbers, never a MAC or an address
before = linkview.tally()
linkview.note("used", 2)
linkview.note("unused", reason="young")
linkview.note("unused", 3, reason="young")
after = linkview.tally()
assert after["used"] - before.get("used", 0) == 2 and after["unused"]["young"] - before.get("unused", {}).get("young", 0) == 4, after
assert set(after) <= {"cycles", "used", "unused", "other_at_address", "found_elsewhere", "moved", "pushed"}, after

# the reasons a link is not used are a closed list (the export counts them)
assert set(linkview.REASONS) == {"none", "held", "seq", "network", "young", "unjudged", "kind", "released"}, linkview.REASONS
print("TUTTO OK")
