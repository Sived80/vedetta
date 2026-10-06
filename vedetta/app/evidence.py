"""Evidence card: for a device, what decided its name, brand and group, how sure the app is (0-100) and which other
hypotheses it rejected. Everything is derived from what debug mode already shows (routes_ha.device_debug), without a second
scoring: the numbers here are the same ones that decided.

How the certainty is worked out (published in the README so nobody has to trust a number blindly):
- chosen by hand: 100.
- group: how far the best category is from the second one, weighted by how much evidence there is. Best 12 points against 3
  = 75 %; best 2 points and nothing else = 20 %; a tie or too little evidence = 0 (it stays in "Other devices").
  A phone or tablet recognised by its signals: the "mobile" score against the threshold.
- brand: the MAC maker and the name agree, or the device declares it = high; one clue alone = medium.
- name: the weight of the source (a name chosen in Home Assistant or on the device itself counts more than a page title)."""
from . import naming

_MOBILE_FULL_SCORE = 8      # mobile score that fills the bar


def _clamp(value: float, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, int(round(value))))


def group_evidence(debug_type: dict, device: dict) -> dict:
    chosen = debug_type.get("chosen") or "generic"
    scores = {g: p for g, p in (debug_type.get("scores") or {}).items() if p > 0}
    manual = bool(debug_type.get("manual"))
    min_score = debug_type.get("min_score") or 2
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    clues = [{"source": e["source"], "points": e["pts"]} for e in (debug_type.get("evidence") or [])
             if e.get("group") == chosen and e.get("counted")]
    clues.sort(key=lambda c: -c["points"])
    out = {"value": chosen, "clues": clues[:4], "reason": None}

    def rejected(why: str) -> list[dict]:
        top = scores.get(chosen, 0)
        return [{"value": g, "points": p, "why": why if why != "scored" else ("tie" if p == top and top else "behind")}
                for g, p in ranked if g != chosen]

    if manual:
        return {**out, "certainty": 100, "basis": "manual", "rejected": rejected("scored")}
    if device.get("is_mobile") and chosen == "phone":
        score = device.get("mobile_score")
        if score is None:                      # chosen by hand in the "mobile" switch
            return {**out, "certainty": 100, "basis": "manual", "rejected": rejected("mobile")}
        return {**out, "certainty": _clamp(100 * score / _MOBILE_FULL_SCORE, 25, 95), "basis": "mobile",
                "reason": device.get("mobile_reason"), "rejected": rejected("mobile")}
    if not ranked:
        return {**out, "certainty": 0, "basis": "none", "rejected": []}
    if chosen == "generic":
        top = ranked[0][1]
        basis = "weak" if top < min_score else "tie"
        return {**out, "certainty": 0, "basis": basis, "rejected": [{"value": g, "points": p, "why": basis} for g, p in ranked]}
    top = scores.get(chosen, ranked[0][1])
    second = next((p for g, p in ranked if g != chosen), 0)
    lead = (top - second) / top if top else 0
    return {**out, "certainty": _clamp(100 * lead * min(1.0, top / 10), 5, 99), "basis": "scored", "rejected": rejected("scored")}


def brand_evidence(debug_brand: dict) -> dict:
    brand = debug_brand.get("brand")
    source = debug_brand.get("source")
    out = {"value": brand, "source": source, "rejected": []}
    vendor, declared = debug_brand.get("vendor"), debug_brand.get("declared")
    if vendor and (not brand or vendor.lower() != brand.lower()):
        out["rejected"].append({"kind": "vendor", "value": vendor, "role": debug_brand.get("vendor_role")})
    if declared and (not brand or declared.lower() != brand.lower()):
        out["rejected"].append({"kind": "declared", "value": declared, "role": None})
    if debug_brand.get("manual"):
        return {**out, "certainty": 100, "basis": "manual"}
    if not brand:
        return {**out, "certainty": 0, "basis": "none"}
    base = 85 if debug_brand.get("evidence") == "confirmed" else 50
    base += {"high": 10, "medium": 0, "low": -5}.get(debug_brand.get("confidence"), 0)
    return {**out, "certainty": _clamp(base, 10, 98), "basis": "found"}


def name_evidence(debug_name: dict, device: dict) -> dict:
    shown, source = debug_name.get("shown"), debug_name.get("source")
    out = {"value": shown, "source": source, "placeholder": bool(debug_name.get("placeholder"))}
    out["rejected"] = [{"source": c["source"], "value": c["raw"], "cleaned": c.get("cleaned")}
                       for c in (debug_name.get("candidates") or [])
                       if c.get("raw") and c["raw"] != shown and (c.get("cleaned") or "").lower() != (shown or "").lower()]
    if not shown or shown == device.get("ip"):
        return {**out, "certainty": 0, "basis": "ip"}
    if source == "user":
        return {**out, "certainty": 100, "basis": "manual"}
    brand = (device.get("brand") or "").strip().lower()
    if brand and shown.strip().lower() == brand and source in (None, "weak"):
        return {**out, "certainty": 10, "basis": "brand"}      # no real name: the brand stands in
    if debug_name.get("placeholder"):
        return {**out, "certainty": 15, "basis": "placeholder"}
    weight = naming.PRIORITY.get(source or "", 0)
    return {**out, "certainty": _clamp(weight, 20, 95), "basis": "source" if source else "unknown"}


def summarize(debug: dict, device: dict) -> dict:
    """The evidence card for a device from its debug data."""
    return {"name": name_evidence(debug.get("name") or {}, device),
            "brand": brand_evidence(debug.get("brand") or {}),
            "group": group_evidence(debug.get("type") or {}, device)}
