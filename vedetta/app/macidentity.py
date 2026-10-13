"""Single MAC layer, phase 3: are two MACs the same physical device? Probabilistic record linkage (Fellegi-Sunter), pure functions, no brand.

Every piece of evidence has a weight log2(m / u) when two MACs agree on it and log2((1 - m) / (1 - u)) when they disagree, where
  m = chance that two MACs of the SAME device agree on that field (a constant: the field is usually stable on one device),
  u = chance that two RANDOM MACs of this very network agree on that VALUE, estimated from the observed population (smoothed, with a floor).
A value shared by many devices (a generic name, the parameter list of a whole OS family) gets a small weight on its own, a rare one a large
weight: no list of brands or of generic names is needed, the network itself says what is common. A field missing on one side is omitted.
Weights add to a prior; the total gives the zones "same", "possible" (some evidence, not enough: nothing is merged), "different" (evidence against)
and "unrelated" (nothing in common). "Same" also needs STRONG evidence: a shared client identifier, or two independent fields in agreement: one rare
value is not enough, two devices of the same rare model exist and one switching off while the other switches on looks exactly like one device.

Evidence used (all visible to a passive LAN observer): DHCP host name (opt 12), the joint fingerprint of vendor class (opt 60) and parameter
request list (opt 55), client identifier (opt 61, when recorded), and the TIME PATTERN of the two MACs: never active together and one starting right where the
other stopped (a device switching its address on command, capped: alone it never merges), or active together at different addresses (two
devices, unless they share a client identifier: that is one host with two cards). The constants are first guesses to be calibrated on labelled data."""
import math
from collections import Counter
from itertools import combinations

# vendor class (opt 60) and parameter request list (opt 55) both describe the OS family, so they are ONE joint "fingerprint" (counting them as two
# independent proofs would double the weight of the same fact).
FIELDS = ("hostname", "fingerprint", "client_id")
M_AGREE = 0.95            # P(agree on a field | same device, both have it)
# A DHCP client identifier is unique per device by design (RFC 4361: DUID + IAID), so two MACs that carry the same one are the same device whatever
# the size of the network: its chance of agreeing between different devices is capped very low.
FIELD_U_CAP = {"client_id": 0.001}
# Two different devices of the same model, or with the same name, do exist: however rare a value looks in this sample, it never weighs more than this.
FIELD_U_FLOOR = {"hostname": 0.02, "fingerprint": 0.05}
# In a small network a few devices make any value look rare or common by chance: the estimate is pulled towards a prior chance U0 as if K
# extra pairs had been seen (Bayesian smoothing); the more devices, the less the prior counts.
SMOOTH_PAIRS, U0 = 10, 0.1
PRIOR_LOGODDS = -4.0      # most pairs of MACs are different devices
SAME_AT = 5.0             # total log2-odds at or above (and with strong evidence): same device
DIFFERENT_AT = -2.0       # at or below (with evidence against): different devices
HANDOFF_GAP_S = 600       # "one starts where the other stopped"
SIMULTANEOUS_PENALTY = 4.0
HANDOFF_MAX_WEIGHT = 3.0   # a handover alone never merges two MACs: a device that is replaced looks the same
STRONG_FIELDS = 2          # independent fields in agreement needed for "same" when there is no shared client identifier


def estimate_u(features: dict[str, dict]) -> dict[str, dict]:
    """Per field and per VALUE: chance that two random MACs of this network both carry that value (smoothed, floored, capped). A name shared by
    many devices (the generic one, the parameter list of a whole OS family) comes out high, a rare one low, so each value weighs what it is worth."""
    u = {}
    for f in FIELDS:
        values = [v[f] for v in features.values() if v.get(f)]
        pairs = len(values) * (len(values) - 1) / 2
        u[f] = {val: min(max((c * (c - 1) / 2 + SMOOTH_PAIRS * U0) / (pairs + SMOOTH_PAIRS), FIELD_U_FLOOR.get(f, 0.0)), FIELD_U_CAP.get(f, 1.0))
                for val, c in Counter(values).items()}
    return u


def _sessions(f: dict) -> list[tuple[float, float, tuple]]:
    """The activity of a MAC as sorted (start, end, addresses); without sessions, one span from the first to the last time seen."""
    s = f.get("sessions") or [(f["first"], f["last"], tuple(f.get("ips") or ()))]
    return sorted(s, key=lambda x: x[0])


def _relation(sa: list, sb: list) -> tuple[bool, float | None]:
    """(were they active together at different addresses?, smallest gap in seconds between a session of one and a session of the other, None if
    they were ever active together). Two pointers over the sorted sessions: linear, not quadratic."""
    i = j = 0
    together = overlap = False
    gap = None
    while i < len(sa) and j < len(sb):
        s0, e0, ia = sa[i]
        s1, e1, ib = sb[j]
        if min(e0, e1) > max(s0, s1):
            overlap = True
            if not (set(ia) & set(ib)):
                together = True
        else:
            g = max(s0, s1) - min(e0, e1)
            gap = g if gap is None else min(gap, g)
        if e0 < e1:
            i += 1
        else:
            j += 1
    return together, (None if overlap else gap)


def score(a: dict, b: dict, u: dict[str, dict], u_handoff: float = 0.05, rel: tuple | None = None) -> tuple[float, list[str], bool, bool, bool]:
    """Total log2-odds that MAC a and MAC b are the same device, the reasons, whether there is any evidence, whether any is against, and whether
    the evidence for is strong. a and b: {field: value, "first", "last", "ips", "sessions"}. `rel` = _relation(a, b) when already known."""
    why: list[str] = []
    s, evidence, against, agree = _score_fields(a, b, u, PRIOR_LOGODDS, why)
    cid = "client_id" in agree
    s, time_evidence, time_against = _score_time(a, b, s, why, cid, u_handoff, rel)
    strong = cid or len([f for f in agree if f != "client_id"]) >= STRONG_FIELDS
    return s, why, evidence or time_evidence, against or time_against, strong


def _score_fields(a: dict, b: dict, u: dict[str, dict], s: float, why: list[str]) -> tuple[float, bool, bool, list[str]]:
    """Adds, in order, the weight of every field present on both sides to s and its reason to `why`. Returns (s, any evidence, any against, fields in agreement)."""
    evidence = against = False
    agree = []
    for f in FIELDS:
        va, vb = a.get(f), b.get(f)
        if not va or not vb:
            continue
        w = _field_weight(va, vb, u[f])
        if va == vb:
            agree.append(f)
        s += w
        evidence, against = True, against or w < 0
        why.append(f"{f} {'uguale' if va == vb else 'diverso'} ({w:+.1f})")
    return s, evidence, against, agree


def _field_weight(va, vb, uf: dict) -> float:
    """Log2-odds of one field present on both sides: agreement weighs more the rarer the value; disagreement weighs less against the more common the two values."""
    if va == vb:
        return math.log2(M_AGREE / uf.get(va, 0.5))
    uv = max(uf.get(va, 0.5), uf.get(vb, 0.5))
    return math.log2((1 - M_AGREE) / (1 - uv))


def _score_time(a: dict, b: dict, s: float, why: list[str], cid: bool, u_handoff: float, rel: tuple | None) -> tuple[float, bool, bool]:
    """Adds the time pattern of the two MACs to s and its reason to `why`. Returns (s, evidence, against); nothing changes when either has no activity data."""
    if "first" not in a or "first" not in b:
        return s, False, False
    together, gap = rel if rel is not None else _relation(_sessions(a), _sessions(b))
    if together and not cid:
        why.append(f"attivi insieme su indirizzi diversi ({-SIMULTANEOUS_PENALTY:+.1f})")
        return s - SIMULTANEOUS_PENALTY, True, True
    if together:
        why.append("stesso client id attivo su due indirizzi: un host con due schede")
        return s, False, False
    if gap is not None and gap <= HANDOFF_GAP_S:
        w = min(math.log2(M_AGREE / u_handoff), HANDOFF_MAX_WEIGHT)
        why.append(f"uno inizia dove l'altro finisce ({w:+.1f})")
        return s + w, True, False
    return s, False, False


def zone(s: float, evidence: bool = True, against: bool = True, strong: bool = True) -> str:
    """same (enough weight AND strong evidence) / possible (some evidence for, not enough) / different (evidence against) / unrelated (nothing in common)."""
    if s >= SAME_AT and strong:
        return "same"
    if not evidence:
        return "unrelated"
    return "different" if (s <= DIFFERENT_AT and against) else "possible"


def link(features: dict[str, dict]) -> list[dict]:
    """All pairs of MACs with their score, zone and reasons, best first. features: {mac: {field..., first, last, ips, sessions}}."""
    u = estimate_u(features)
    macs = sorted(features)
    rels = _pair_relations(features, macs)
    u_handoff = _handoff_rate(rels)
    out = []
    for x, y in combinations(macs, 2):
        s, why, evidence, against, strong = score(features[x], features[y], u, u_handoff, rels.get((x, y)))
        out.append({"a": x, "b": y, "score": round(s, 2), "zone": zone(s, evidence, against, strong), "why": why})
    return sorted(out, key=lambda r: -r["score"])


def _pair_relations(features: dict[str, dict], macs: list[str]) -> dict[tuple[str, str], tuple]:
    """_relation of every pair of MACs that both have activity data, once per pair."""
    sess = {m: _sessions(features[m]) for m in macs if "first" in features[m]}
    return {(x, y): _relation(sess[x], sess[y]) for x, y in combinations(macs, 2) if x in sess and y in sess}


def _handoff_rate(rels: dict) -> float:
    """How often two random MACs happen to hand over (smoothed); the default when there is no pair with activity data."""
    if not rels:
        return 0.05
    near = sum(1 for _, gap in rels.values() if gap is not None and gap <= HANDOFF_GAP_S)
    return max((near + 1) / (len(rels) + 2), 0.001)
