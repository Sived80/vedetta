"""The badges of a card's icon: one class per kind, ONE module that decides which are shown and where, never two in the same corner, at most two in all (the user's choice; alarm
management studies say few and actionable: alarms that are frequent or do not call for action desensitise). The kinds not shown stay in the detail of the card. Pure: it gets
flags, it knows nothing of the rest of the app (the UI chooses colours for both themes and always adds a text or a shape, never colour alone).
Corners: top_right = the state of the device (don't touch, fragile, under analysis); bottom_right = what is new or still settling."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.analysis import badges  # noqa: E402


def shown(**flags):
    return [(b.id, b.corner) for b in badges.choose(flags)]


assert shown() == []
assert shown(analysing=True) == [("analysing", "top_right")]
assert shown(no_touch=True) == [("no_touch", "top_right")]
# one per corner: the strongest of the state kinds, the strongest of the others
assert shown(no_touch=True, fragile=True, analysing=True) == [("no_touch", "top_right")], "state kinds compete for ONE corner: don't touch wins over fragile and analysing"
assert shown(fragile=True, analysing=True) == [("fragile", "top_right")]
assert shown(analysing=True, new=True) == [("analysing", "top_right"), ("new", "bottom_right")]
assert shown(settling=True, new=True, twin=7) == [("new", "bottom_right")] and shown(settling=True, twin=7) == [("settling", "bottom_right")]
assert shown(twin=7) == [("twin", "bottom_right")] and badges.choose({"twin": 7})[0].text == "7"
# at most two, in a fixed order (top first), whatever the order of the flags
every = dict(no_touch=True, fragile=True, analysing=True, new=True, settling=True, twin=3)
assert len(badges.choose(every)) == 2 and shown(**every) == [("no_touch", "top_right"), ("new", "bottom_right")]
assert shown(**dict(reversed(list(every.items())))) == shown(**every)
# what did not fit is told, for the detail of the card
assert [b.id for b in badges.hidden(every)] == ["fragile", "analysing", "settling", "twin"], badges.hidden(every)
# an unknown or false flag shows nothing
assert shown(no_touch=False, new=None, mystery=True) == []
# --- unresolved (a card that stayed under analysis for a week): it takes the corner of the state like analysing, and gives way to the stronger kinds
assert shown(unresolved=True) == [("unresolved", "top_right")]
assert shown(no_touch=True, unresolved=True) == [("no_touch", "top_right")] and shown(fragile=True, unresolved=True) == [("fragile", "top_right")]
assert shown(unresolved=True, new=True) == [("unresolved", "top_right"), ("new", "bottom_right")]
print("TUTTO OK")
