"""export_analysis: build the enriched analysis state (state/analysis.json) for diagnosis and privacy.

Strict schema with allowlist validation:
- No raw device names, IPs, MACs, or free-text clues are kept here (except the card id, which is pseudonymized with the rest of the export).
- Enums are strictly validated against an allowlist; unknown values become "other".
- Scores are structured as a list of [group, points] pairs so that group names never become dict keys.
- Read-only access to analysis_view and status thresholds.
"""
import time

from ..analysis import badges as bg_rules, status as st
from ..ha import analysis_view
from ..state import state

ALLOWED_STATES = frozenset({st.IDENTIFIED, st.SETTLING, st.ANALYSING, st.UNRESOLVED})
ALLOWED_REASONS = frozenset({"low_certainty", "thin", "override", "close", "expired"})
ALLOWED_BADGE_IDS = frozenset({"no_touch", "fragile", "analysing", "unresolved", "new", "settling", "twin"})
ALLOWED_GROUPS = frozenset({"router", "phone", "media", "iot", "camera", "generic", "server", "pc", "audio", "printer"})


def _val_enum(val: str | None, allowed: frozenset[str]) -> str | None:
    if val is None:
        return None
    s = str(val).strip().lower()
    return s if s in allowed else "other"


def _val_reasons(reasons: list | tuple | set | None) -> list[str]:
    out: list[str] = []
    for r in reasons or ():
        clean = _val_enum(r, ALLOWED_REASONS)
        if clean and clean not in out:
            out.append(clean)
    return out


def _val_badges(badges_list: list | tuple | None) -> list[str]:
    out: list[str] = []
    for b in badges_list or ():
        bid = b.get("id") if isinstance(b, dict) else getattr(b, "id", str(b))
        clean = _val_enum(bid, ALLOWED_BADGE_IDS)
        if clean and clean not in out:
            out.append(clean)
    return out


def _val_scores(scores: dict | list | None) -> list[list]:
    """Scores as a list of [group, points] pairs, descending by points: avoids enum keys in dicts."""
    out: list[list] = []
    if isinstance(scores, dict):
        for k, v in sorted(scores.items(), key=lambda it: (-it[1] if isinstance(it[1], (int, float)) else 0, str(it[0]))):
            grp = _val_enum(k, ALLOWED_GROUPS) or "other"
            pts = int(v) if isinstance(v, (int, float)) else 0
            out.append([grp, pts])
    elif isinstance(scores, (list, tuple)):
        for item in scores:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                grp = _val_enum(item[0], ALLOWED_GROUPS) or "other"
                pts = int(item[1]) if isinstance(item[1], (int, float)) else 0
                out.append([grp, pts])
    return out


def build_analysis_snapshot(now: float | None = None) -> dict:
    """Build the state/analysis.json payload according to the strict privacy specifications."""
    now = time.time() if now is None else now
    thresholds = {
        "low": st.LOW,
        "high": st.HIGH,
        "grace_s": st.GRACE_S,
        "max_s": st.MAX_ANALYSIS_S,
        "close_points": st.CLOSE_POINTS,
    }
    cards = []
    try:
        inputs = analysis_view.collect(list(state.devices), now)
        results = dict(analysis_view.RESULTS)
        clocks = dict(analysis_view._since)

        for card_id, inp in sorted(inputs.items(), key=lambda it: it[0]):
            res = results.get(card_id)
            if res is None:
                continue

            state_val = _val_enum(res.state, ALLOWED_STATES) or "other"
            reasons_val = _val_reasons(res.reasons)
            flags = analysis_view._flags(res)
            chosen_badges = bg_rules.choose(flags)
            badges_val = _val_badges([b.id for b in chosen_badges])
            scores_val = _val_scores(inp.get("scores"))
            chosen_val = _val_enum(inp.get("chosen"), ALLOWED_GROUPS)
            since_val = clocks.get(card_id)
            analysing_for_s = round(now - since_val, 1) if since_val is not None and state_val == st.ANALYSING else None
            age_s = round(inp["age_s"], 1) if isinstance(inp.get("age_s"), (int, float)) and inp["age_s"] < analysis_view.OLD_S else None

            cards.append({
                "id": card_id,
                "state": state_val,
                "reasons": reasons_val,
                "badges": badges_val,
                "scores": scores_val,
                "chosen": chosen_val,
                "since": round(since_val, 1) if since_val is not None else None,
                "analysing_for_s": analysing_for_s,
                "age_s": age_s,
            })
    except Exception:
        # Never leak exception details or raw traces
        return {
            "version": 1,
            "generated": round(now, 1),
            "thresholds": thresholds,
            "cards": [],
            "status": "unavailable",
        }

    return {
        "version": 1,
        "generated": round(now, 1),
        "thresholds": thresholds,
        "cards": cards,
    }
