"""Evidence card: certainty and rejected hypotheses come from the same numbers that decided, and the sheet shows them."""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.recognition import evidence
from app.routes import ha as routes_ha  # noqa: E402
from app.state import state  # noqa: E402


def typ(chosen, scores, manual=None, evidence_rows=()):
    return {"chosen": chosen, "manual": manual, "scores": scores, "evidence": list(evidence_rows), "min_score": 2, "margin_below": 5}


rows = [{"group": "router", "source": "ruolo di rete", "pts": 8, "family": "role", "counted": True},
        {"group": "router", "source": "porta 80", "pts": 4, "family": "port:80", "counted": True},
        {"group": "iot", "source": "mDNS _hap._tcp", "pts": 3, "family": "svc", "counted": True}]
g = evidence.group_evidence(typ("router", {"router": 12, "iot": 3}, evidence_rows=rows), {})
assert g["basis"] == "scored" and g["certainty"] == 75 and g["rejected"] == [{"value": "iot", "points": 3, "why": "behind"}], g
assert [c["source"] for c in g["clues"]] == ["ruolo di rete", "porta 80"]
assert evidence.group_evidence(typ("iot", {"iot": 2}), {})["certainty"] == 20            # little evidence, nobody against
assert evidence.group_evidence(typ("router", {"router": 12, "iot": 12}), {})["rejected"][0]["why"] == "tie"
# generic: weak or tied, certainty 0, everything is rejected
w = evidence.group_evidence(typ("generic", {"iot": 1}), {})
assert w["basis"] == "weak" and w["certainty"] == 0 and w["rejected"][0]["why"] == "weak"
assert evidence.group_evidence(typ("generic", {"iot": 3, "media": 3}), {})["basis"] == "tie"
assert evidence.group_evidence(typ("generic", {}), {})["basis"] == "none"
# by hand
m = evidence.group_evidence(typ("server", {"router": 12}, manual="server"), {})
assert m["basis"] == "manual" and m["certainty"] == 100 and m["rejected"][0]["value"] == "router"
# phones: the mobile score against its threshold; chosen by hand in the switch = 100
p = evidence.group_evidence(typ("phone", {"iot": 3}), {"is_mobile": True, "mobile_score": 6, "mobile_reason": "MAC privati diversi"})
assert p["basis"] == "mobile" and p["certainty"] == 75 and p["reason"] == "MAC privati diversi" and p["rejected"][0]["why"] == "mobile", p
assert evidence.group_evidence(typ("phone", {}), {"is_mobile": True, "mobile_score": 3})["certainty"] == 38
assert evidence.group_evidence(typ("phone", {}), {"is_mobile": True, "mobile_score": None})["basis"] == "manual"

# brand
b = evidence.brand_evidence({"brand": "Shelly", "source": "name", "evidence": "confirmed", "confidence": "high", "vendor": "Espressif",
                             "vendor_role": "component", "declared": None})
assert b["certainty"] == 95 and b["basis"] == "found" and b["rejected"] == [{"kind": "vendor", "value": "Espressif", "role": "component"}], b
assert evidence.brand_evidence({"brand": "X", "evidence": "plausible", "confidence": "low"})["certainty"] == 45
assert evidence.brand_evidence({"brand": "X", "manual": "X"})["certainty"] == 100
n0 = evidence.brand_evidence({"brand": None, "vendor": "Foo", "declared": "Bar"})
assert n0["certainty"] == 0 and n0["basis"] == "none" and {r["kind"] for r in n0["rejected"]} == {"vendor", "declared"}

# name
nm = evidence.name_evidence({"shown": "Thermostat", "source": "mdns", "placeholder": False,
                             "candidates": [{"source": "mdns", "raw": "Thermostat", "cleaned": "Thermostat"},
                                            {"source": "dhcp", "raw": "esp32-abc123", "cleaned": None},
                                            {"source": "web", "raw": "Main Menu", "cleaned": "Main Menu"}]}, {"ip": "10.0.0.5"})
assert nm["certainty"] == 70 and nm["basis"] == "source" and [r["source"] for r in nm["rejected"]] == ["dhcp", "web"], nm
assert evidence.name_evidence({"shown": "10.0.0.5", "source": None}, {"ip": "10.0.0.5"})["basis"] == "ip"
assert evidence.name_evidence({"shown": "Anna", "source": "user"}, {})["certainty"] == 100
assert evidence.name_evidence({"shown": "Android", "source": "mdns", "placeholder": True}, {})["basis"] == "placeholder"
bn = evidence.name_evidence({"shown": "Apple", "source": None}, {"brand": "Apple", "ip": "10.0.0.5"})
assert bn["basis"] == "brand" and bn["certainty"] == 10        # the brand stands in for a name nobody gave
assert evidence.name_evidence({"shown": "Apple", "source": "user"}, {"brand": "Apple"})["certainty"] == 100

# the whole card, and the route (404 for an unknown device)
card = evidence.summarize({"type": typ("router", {"router": 12}), "name": {"shown": "R", "source": "adapter"}, "brand": {"brand": "AVM", "evidence": "confirmed"}}, {})
assert set(card) == {"name", "brand", "group"} and json.dumps(card)
try:
    asyncio.run(routes_ha.api_ha_device_evidence("does-not-exist"))
    raise AssertionError("an unknown device must be a 404")
except routes_ha.HTTPException as exc:
    assert exc.status_code == 404
state.devices.clear()
print("TUTTO OK")
