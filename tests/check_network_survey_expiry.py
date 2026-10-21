"""The switch of the network survey has a review date. Past it, this test fails until someone decides: turn the survey off (ENABLED = False) or move the date,
with the reason written in DECISIONI.md. A switch that is never looked at again is a cost (feature toggles are inventory: remove them when they have done their job)."""
import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.export import network_survey as ns  # noqa: E402

assert isinstance(ns.REVIEW_BY, datetime.date)
if ns.ENABLED and datetime.date.today() > ns.REVIEW_BY:
    sys.exit(f"the network survey is still on after its review date {ns.REVIEW_BY}: turn it off or move the date (and say why in DECISIONI.md)")
print("TUTTO OK")
