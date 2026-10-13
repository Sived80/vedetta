"""Evidence card: for a device, what decided its name, brand and group, how sure the app is (0-100) and which other
hypotheses it rejected. Everything is derived from what debug mode already shows (ha/device_debug.py), without a second
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


def _rejected_groups(ranked: list, scores: dict, chosen: str, why: str) -> list[dict]:
    """The other groups, with why each was not chosen ("scored" is told apart into tie / behind by the points of the chosen one)."""
    top = scores.get(chosen, 0)
    return [{"value": g, "points": p, "why": why if why != "scored" else ("tie" if p == top and top else "behind")}
            for g, p in ranked if g != chosen]


def group_evidence(debug_type: dict, device: dict) -> dict:
    chosen = debug_type.get("chosen") or "generic"
    scores = _positive_scores(debug_type)
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    out = {"value": chosen, "clues": _top_clues(debug_type, chosen), "reason": None}
    decided = _manual_or_mobile(out, device, ranked, scores, chosen, bool(debug_type.get("manual")))
    if decided is not None:
        return decided
    if not ranked:
        return {**out, "certainty": 0, "basis": "none", "rejected": []}
    return _scored_group(out, ranked, scores, chosen, debug_type.get("min_score") or 2)


def _manual_or_mobile(out: dict, device: dict, ranked: list, scores: dict, chosen: str, manual: bool) -> dict | None:
    """The groups chosen by hand, and the phones and tablets recognised by their signals; None for the rest."""
    if manual:
        return {**out, "certainty": 100, "basis": "manual", "rejected": _rejected_groups(ranked, scores, chosen, "scored")}
    if device.get("is_mobile") and chosen == "phone":
        score = device.get("mobile_score")
        if score is None:                      # chosen by hand in the "mobile" switch
            return {**out, "certainty": 100, "basis": "manual", "rejected": _rejected_groups(ranked, scores, chosen, "mobile")}
        return {**out, "certainty": _clamp(100 * score / _MOBILE_FULL_SCORE, 25, 95), "basis": "mobile",
                "reason": device.get("mobile_reason"), "rejected": _rejected_groups(ranked, scores, chosen, "mobile")}
    return None


def _scored_group(out: dict, ranked: list, scores: dict, chosen: str, min_score: int) -> dict:
    """The group chosen by the scores: how far it is from the second one, weighted by how much evidence there is."""
    if chosen == "generic":
        top = ranked[0][1]
        basis = "weak" if top < min_score else "tie"
        return {**out, "certainty": 0, "basis": basis, "rejected": [{"value": g, "points": p, "why": basis} for g, p in ranked]}
    top = scores.get(chosen, ranked[0][1])
    second = next((p for g, p in ranked if g != chosen), 0)
    lead = (top - second) / top if top else 0
    return {**out, "certainty": _clamp(100 * lead * min(1.0, top / 10), 5, 99), "basis": "scored", "rejected": _rejected_groups(ranked, scores, chosen, "scored")}


def _positive_scores(debug_type: dict) -> dict:
    """The groups that scored something (zero or negative points are left out)."""
    return {g: p for g, p in (debug_type.get("scores") or {}).items() if p > 0}


def _top_clues(debug_type: dict, chosen: str) -> list[dict]:
    """The (at most four) counted clues of the chosen group, strongest first (equal points keep their order)."""
    clues = [{"source": e["source"], "points": e["pts"]} for e in (debug_type.get("evidence") or [])
             if e.get("group") == chosen and e.get("counted")]
    clues.sort(key=lambda c: -c["points"])
    return clues[:4]


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
                       for c in (debug_name.get("candidates") or []) if _is_rejected_name(c, shown)]
    certainty, basis = _name_certainty(debug_name, device, shown, source)
    return {**out, "certainty": certainty, "basis": basis}


def _is_rejected_name(candidate: dict, shown) -> bool:
    """A name candidate that was not shown: it has a raw value, different from the shown one both as it is and once cleaned."""
    return bool(candidate.get("raw") and candidate["raw"] != shown
                and (candidate.get("cleaned") or "").lower() != (shown or "").lower())


def _name_certainty(debug_name: dict, device: dict, shown, source) -> tuple[int, str]:
    """(certainty, basis) of the shown name."""
    if not shown or shown == device.get("ip"):
        return 0, "ip"
    if source == "user":
        return 100, "manual"
    if _brand_stands_in(device, shown, source):
        return 10, "brand"      # no real name: the brand stands in
    if debug_name.get("placeholder"):
        return 15, "placeholder"
    weight = naming.PRIORITY.get(source or "", 0)
    return _clamp(weight, 20, 95), "source" if source else "unknown"


def _brand_stands_in(device: dict, shown, source) -> bool:
    """No real name: the shown name is just the brand, and the source is none or a weak one."""
    brand = (device.get("brand") or "").strip().lower()
    return bool(brand) and shown.strip().lower() == brand and source in (None, "weak")


def summarize(debug: dict, device: dict) -> dict:
    """The evidence card for a device from its debug data."""
    return {"name": name_evidence(debug.get("name") or {}, device),
            "brand": brand_evidence(debug.get("brand") or {}),
            "group": group_evidence(debug.get("type") or {}, device)}
