"""The rules of the Sentinel (app/sentinel.py), scenario by scenario: which changes become a message, and when.
    python tests/check_sentinel.py"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.sentinel import BACK, DOWN, NEW, PENDING, SENT, SUPPRESSED, DEFAULT_RULES, Rules, Sentinel  # noqa: E402

R = Rules(down_delay_s=300, sleep_s=1800, flap_count=3, flap_window_s=3600, unstable_wait_s=900)
offline: set = set()
sleepy: set = set()


def due(s, now):
    ready = s.due(now, lambda c: c in offline, lambda c: c in sleepy)
    s.mark_sent(ready, now)
    return [(e["kind"], e["card"]) for e in ready]


def go(s, card, online, now, watched=True):
    (offline.discard if online else offline.add)(card)
    s.presence(card, online, now, watched=watched, label=card)


def states(s, card):
    return [(e["kind"], e["state"], e.get("reason")) for e in s.events if e["card"] == card]


# 1) a new device: sent at the first cycle, once
s = Sentinel(R)
s.new_device("aa:bb", 0, label="Pixel", ip="10.0.0.9")
assert due(s, 1) == [(NEW, "aa:bb")] and due(s, 2) == []

# 2) a watched card down: born at once, sent only after 5 minutes still offline
s = Sentinel(R)
go(s, "nas", False, 1000)
assert due(s, 1000) == [] and due(s, 1299) == []
assert due(s, 1300) == [(DOWN, "nas")] and due(s, 1400) == []
go(s, "nas", True, 2000)                                   # back after a SENT down: "back", with how long it was away
assert due(s, 2001) == [(BACK, "nas")]
back = [e for e in s.events if e["kind"] == BACK][0]
assert back["params"]["away_s"] == 1000

# 3) it comes back before the delay: no "down", and so no "back" either
s = Sentinel(R)
go(s, "tv", False, 0)
go(s, "tv", True, 120)
assert due(s, 400) == [] and states(s, "tv") == [(DOWN, SUPPRESSED, "returned")]

# 4) a card not watched: nothing for down or back
s = Sentinel(R)
go(s, "plug", False, 0, watched=False)
go(s, "plug", True, 900, watched=False)
assert due(s, 1000) == [] and s.events == []

# 5) a card that may sleep (a phone): 5 + 30 minutes before "down"
s = Sentinel(R)
sleepy.add("phone")
go(s, "phone", False, 0)
assert due(s, 300) == [] and due(s, 2099) == [] and due(s, 2100) == [(DOWN, "phone")]
# with the rules of the app: a watched phone is "down" after 10 minutes in all, any other card after 5
s = Sentinel(DEFAULT_RULES)
go(s, "phone", False, 0)
assert due(s, 599) == [] and due(s, 600) == [(DOWN, "phone")]
sleepy.clear()
s = Sentinel(DEFAULT_RULES)
go(s, "cam", False, 0)
assert due(s, 299) == [] and due(s, 300) == [(DOWN, "cam")]

# 6) one "down" per absence: a second offline without an online adds nothing
s = Sentinel(R)
go(s, "cam", False, 0)
s.presence("cam", False, 10, watched=True)
assert len([e for e in s.events if e["kind"] == DOWN]) == 1

# 7) unstable (3 changes in an hour): the down waits 15 minutes of absence in a row instead of 5, then it is sent (it no longer
#    waits for the changes to leave the hour: a flaky card that really goes away is told, only later; the user's test of 17/11)
s = Sentinel(R)
go(s, "wifi", False, 0)
go(s, "wifi", True, 60)
go(s, "wifi", False, 120)                                  # third change in the hour: unstable
assert s.unstable("wifi", 500) and due(s, 500) == []       # 380 s offline, but unstable: waits
assert due(s, 1019) == [] and due(s, 1020) == [(DOWN, "wifi")]   # 15 minutes after the last offline: sent
s = Sentinel(R)                                             # unstable and back before the 15 minutes: nothing
go(s, "wifi", False, 0)
go(s, "wifi", True, 60)
go(s, "wifi", False, 120)
go(s, "wifi", True, 900)
assert due(s, 1100) == [] and states(s, "wifi")[-1][1:] == (SUPPRESSED, "returned")
s = Sentinel(R)                                             # an unstable phone: its own wait (5 + 30 here) is longer, it wins
sleepy.add("ph")
go(s, "ph", False, 0)
go(s, "ph", True, 60)
go(s, "ph", False, 120)
assert due(s, 1020) == [] and due(s, 120 + 2100) == [(DOWN, "ph")]
sleepy.clear()

# 8) a SUPPRESSED down never gives a "back" (silenced, then back)
s = Sentinel(R)
s.silence("nas", until=5000)
go(s, "nas", False, 0)
assert due(s, 400) == [] and states(s, "nas") == [(DOWN, SUPPRESSED, "silenced")]
go(s, "nas", True, 6000)
assert due(s, 6001) == [] and [k for k, *_ in states(s, "nas")] == [DOWN]

# 9) after a back, a new absence is a new "down"
s = Sentinel(R)
go(s, "nas", False, 0)
due(s, 300)
go(s, "nas", True, 400)
due(s, 401)
go(s, "nas", False, 10000)
assert due(s, 10300) == [(DOWN, "nas")]

# 10) a card that stops being watched while away: no "back", and the absence is closed
s = Sentinel(R)
go(s, "nas", False, 0)
due(s, 300)
go(s, "nas", True, 500, watched=False)
assert due(s, 501) == [] and s._open_down("nas") is None

# 11) several events in one cycle: one call to due gives them all, oldest first
s = Sentinel(R)
s.new_device("m1", 0)
go(s, "a", False, 0)
go(s, "b", False, 10)
assert due(s, 400) == [(NEW, "m1"), (DOWN, "a"), (DOWN, "b")]

# 12) the state survives a restart (JSON): a down sent before still gives its back after
s = Sentinel(R)
go(s, "nas", False, 0)
due(s, 300)
s2 = Sentinel.from_json(json.loads(json.dumps(s.to_json())), R)
go(s2, "nas", True, 900)
assert due(s2, 901) == [(BACK, "nas")]
s2.new_device("x", 902)
assert max(e["id"] for e in s2.events) == len(s2.events)       # ids go on after the restart, never reused
for junk in (None, [], "x", {"events": "x"}, {"events": [{"id": 1}]}, {"changes": {"a": ["x"]}}):
    assert Sentinel.from_json(junk, R).events == [] or junk == {"events": [{"id": 1}]}

# 13) prune: finished events older than a week go, pending ones stay
s = Sentinel(R)
s.new_device("old", 0)
due(s, 1)
go(s, "nas", False, 2)
s.prune(8 * 86400)
assert [e["kind"] for e in s.events] == [DOWN] and s.events[0]["state"] == PENDING

# 18/11 review: a watched NAS away for 8 days: its sent "down" is kept past the week, so its return still says "back"
s = Sentinel(R)
go(s, "nas2", False, 0)
assert due(s, 300) == [(DOWN, "nas2")]
s.prune(8 * 86400)
go(s, "nas2", True, 8 * 86400 + 10)
assert due(s, 8 * 86400 + 11) == [(BACK, "nas2")], states(s, "nas2")
s.prune(16 * 86400 + 20)                                    # closed by its "back": both go after their week
assert not [e for e in s.events if e["card"] == "nas2"], states(s, "nas2")
# a card deleted while away never closes its "down": it goes after OPEN_DOWN_MAX_S, not never (18/11 review)
s = Sentinel(R)
go(s, "gone", False, 0)
assert due(s, 300) == [(DOWN, "gone")]
s.prune(89 * 86400)
assert states(s, "gone"), "kept while it may still come back"
s.prune(91 * 86400)
assert not states(s, "gone"), states(s, "gone")

# a card deleted while away: its down is closed, so a new card with the same id (the same address) starts clean (18/11 review 3)
s = Sentinel(R)
go(s, "scan-10-0-0-50", False, 0)
assert due(s, 300) == [(DOWN, "scan-10-0-0-50")]
s.forget_gone({"other"}, 400)
go(s, "scan-10-0-0-50", True, 500)                          # the new device at that address answers: no bogus "back"
assert due(s, 501) == [], states(s, "scan-10-0-0-50")
go(s, "scan-10-0-0-50", False, 600)                         # and its own absence gives its own "down"
assert due(s, 1500) == [(DOWN, "scan-10-0-0-50")], states(s, "scan-10-0-0-50")     # three changes in the hour: unstable, 15 minutes
# the time of the last message about each card is dropped after a week like the finished events: a guest's rotating MACs must not make
# sentinel.json grow for ever (19/11 review)
s = Sentinel(R)
s.sent_at = {"old-card": 0.0, "recent-card": 8 * 86400.0}
s.prune(8 * 86400.0 + 60)
assert s.sent_at == {"recent-card": 8 * 86400.0}, s.sent_at
print("check_sentinel: ok")
