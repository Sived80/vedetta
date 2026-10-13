"""Analysis, phase 1 (read-only): from what the evidence card already says, is a device identified, settling (too young to judge) or under analysis? Pure, no network.
Shape of the rule (see PROGETTO_ANALISI and PRATICA_CORRETTA part 2): two thresholds with a middle zone (Fellegi-Sunter): below the low one it enters analysis, above the high one it
leaves, between them it keeps the state it had (hysteresis, as Nagios does for flapping); a grace period for a card that has just appeared (cold start); a device typed by the user is identified.
Real shapes: a young install where eight cards of 21 had a low certainty after 21 minutes; a repeater with an override (the mobile score won over the router points)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.analysis import status as st  # noqa: E402

H = 3600.0


RIVAL = [{"value": "server", "points": 2, "why": "behind"}]


def group(certainty, basis="scored", value="router", rejected=None, clues=10):
    return {"value": value, "certainty": certainty, "basis": basis, "clues": [{"source": "x", "points": clues}], "rejected": rejected or []}


def judge(g, age_s=48 * H, previous=None, scores=None, chosen=None):
    return st.assess(g, age_s=age_s, previous=previous, scores=scores, chosen=chosen)


# a solid card is identified
assert judge(group(80)).state == st.IDENTIFIED and judge(group(80)).reasons == []

# low certainty: under analysis once the grace period is over; before it the card is only settling
low = judge(group(40, rejected=RIVAL))
assert low.state == st.ANALYSING and low.reasons == ["low_certainty"], low
young = judge(group(40, rejected=RIVAL), age_s=10 * 60)
assert young.state == st.SETTLING and young.reasons == ["low_certainty"], young

# two thresholds: between them the card keeps what it was
assert judge(group(55, rejected=RIVAL), previous=st.ANALYSING).state == st.ANALYSING       # still analysing: not yet above the high threshold
assert judge(group(55), previous=st.IDENTIFIED).state == st.IDENTIFIED     # still identified: not yet below the low one
assert judge(group(55)).state == st.IDENTIFIED                              # no history: benefit of the doubt in the middle zone
assert judge(group(65, rejected=RIVAL), previous=st.ANALYSING).state == st.IDENTIFIED      # above the high threshold it leaves analysis
assert judge(group(45, rejected=RIVAL), previous=st.IDENTIFIED).state == st.ANALYSING      # below the low threshold it enters

# conflict between the pieces of evidence is enough even when the certainty is high (the repeater that became a phone)
scores = {"router": 17, "server": 1}
conflict = judge(group(94), scores=scores, chosen="phone")
assert conflict.state == st.ANALYSING and conflict.reasons == ["override"], conflict
tie = judge(group(80, rejected=[{"value": "server", "points": 9, "why": "behind"}]))
assert tie.state == st.ANALYSING and tie.reasons == ["close"], tie
far = judge(group(80, rejected=[{"value": "server", "points": 3, "why": "behind"}]))
assert far.state == st.IDENTIFIED

# the conflicts count even in the grace period (they are not a matter of age)
assert judge(group(94), age_s=60, scores=scores, chosen="phone").state == st.ANALYSING

# a type chosen by the user is identified, whatever the numbers say
assert judge(group(0, basis="manual")).state == st.IDENTIFIED and judge(group(100, basis="manual"), scores=scores, chosen="phone").state == st.IDENTIFIED

# both reasons are listed, in a fixed order
both = judge(group(30, rejected=RIVAL), scores=scores, chosen="phone")
assert both.reasons == ["low_certainty", "override"], both

# thin: a low certainty with no rival group (a smart-home device known by its platform only) is told but opens nothing; no type at all (generic) does open an analysis
thin = judge(group(25, value="iot"))
assert thin.state == st.IDENTIFIED and thin.reasons == ["thin"], thin
assert judge(group(0, value="generic")).state == st.ANALYSING and judge(group(0, value="generic"), age_s=60).state == st.SETTLING

# «close» uses the points that really decided (the group's score), not the four strongest clues shown in the card (found by the review: with more than four clues the sum was too low and «close» fired)
four_clues = {"value": "router", "certainty": 80, "basis": "scored", "clues": [{"source": "x", "points": 2}] * 4, "rejected": [{"value": "server", "points": 9, "why": "behind"}]}
assert judge(four_clues).state == st.ANALYSING and judge(four_clues).reasons == ["close"], "without the real score the clues are all there is"
real = judge(four_clues, scores={"router": 17, "server": 9}, chosen="router")
assert real.state == st.IDENTIFIED and real.reasons == [], real
assert judge(four_clues, scores={"router": 11, "server": 9}, chosen="router").reasons == ["close"]     # really close: 11 against 9

# the thresholds are data, one place
assert st.LOW < st.HIGH and st.GRACE_S > 0
# --- the expiry: a card that has been under analysis for MAX_ANALYSIS_S and still is, is «unresolved»
WEEK = st.MAX_ANALYSIS_S
nothing = {"value": "generic", "certainty": 30, "rejected": [], "basis": "auto"}
assert WEEK == 7 * 86400
assert st.assess(nothing, age_s=10 ** 9, analysing_for_s=WEEK - 1).state == st.ANALYSING, "one second short: still under analysis"
done = st.assess(nothing, age_s=10 ** 9, analysing_for_s=WEEK)
assert done.state == st.UNRESOLVED and done.reasons == ["low_certainty", "expired"], done
assert st.assess(nothing, age_s=10 ** 9).state == st.ANALYSING, "no clock given: no expiry"
# only a card under analysis expires: an identified one, a manual one and a settling one do not
assert st.assess({"value": "router", "certainty": 90, "rejected": [], "basis": "auto"}, age_s=10 ** 9, analysing_for_s=10 * WEEK).state == st.IDENTIFIED
assert st.assess({"value": "router", "certainty": 10, "rejected": [], "basis": "manual"}, age_s=10 ** 9, analysing_for_s=10 * WEEK).state == st.IDENTIFIED
assert st.assess(nothing, age_s=60, analysing_for_s=10 * WEEK).state == st.SETTLING, "a young card is settling whatever the clock says"
# the conflict that keeps a card under analysis keeps it unresolved too, with its own reasons
conflict = st.assess({"value": "phone", "certainty": 62, "rejected": [], "basis": "mobile"}, age_s=10 ** 9, scores={"router": 17}, chosen="phone", analysing_for_s=WEEK)
assert conflict.state == st.UNRESOLVED and conflict.reasons == ["override", "expired"], conflict
# unresolved keeps the hysteresis of analysis: it leaves only above the high threshold, and then it is simply identified
mid = {"value": "router", "certainty": 55, "rejected": [{"value": "pc", "points": 3}], "basis": "auto"}
assert st.assess(mid, age_s=10 ** 9, previous=st.UNRESOLVED, analysing_for_s=WEEK).state == st.UNRESOLVED
assert st.assess(dict(mid, certainty=61), age_s=10 ** 9, previous=st.UNRESOLVED, analysing_for_s=WEEK).state == st.IDENTIFIED
assert st.assess(mid, age_s=10 ** 9, previous=st.IDENTIFIED, analysing_for_s=WEEK).state == st.IDENTIFIED, "a card that was identified needs the low threshold to enter"
print("TUTTO OK")
