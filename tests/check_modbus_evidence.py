"""Energy devices (inverters, meters, wall boxes, batteries) and controllers speak Modbus TCP on port 502 (the port assigned to it; the Modbus Organization's TCP/IP guide).
Seeing the port OPEN is a weak clue for the smart home group, nothing more: it is shared with PLCs and other equipment, so it never decides alone, and nothing is ever sent
to it (rule: never risk commanding a device; see check_no_talk_ports.py). Real case: an inverter with no name and no announcement, found only by its open ports."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import ha_type_evidence as te  # noqa: E402

card = {"ip": "10.0.0.50", "name": "10.0.0.50", "scanned_ports": [{"label": "502 · modbus", "confirmed": False, "category": "other"}]}
found = [e for e in te.type_evidence(dict(card)) if e["family"].startswith("port:502")]
assert found and found[0]["group"] == "iot" and found[0]["pts"] == te.W_PORT_GUESS, found
scores = te.type_scores(dict(card))
assert scores.get("iot") == te.W_PORT_GUESS and scores["iot"] < te.MIN_TYPE_SCORE, "the port alone must not make a type: %s" % scores

# with another clue of the same group (a platform clue, here a local API of a smart-home maker) it can pass the minimum
with_api = dict(card, extra={"api_source": "tasmota"})
assert te.type_scores(with_api).get("iot", 0) >= te.MIN_TYPE_SCORE, te.type_scores(with_api)

# a port that is not Modbus stays as it was
other = dict(card, scanned_ports=[{"label": "8081 · http", "confirmed": False, "category": "web"}])
assert not [e for e in te.type_evidence(other) if e["family"].startswith("port:502")]
print("TUTTO OK")
