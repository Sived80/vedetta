"""Single MAC layer, phase 2: what kind of MAC is this? Pure functions over the rows of ip_mac (no network, no database, no brand).

Input: rows {ip, mac, source, first_seen, last_seen, seen_count} as History.observe stores them, and optionally (phase 2b) the activity SESSIONS
{ip, mac, source, start, end} and the FLIPS {ip, old, new, ts} (every change of the MAC that answers an address). Without sessions and flips it
falls back to the coarse rules on first/last time seen. Output: a kind per MAC and the IP conflicts.
Only universal signals are used (each from a specification or from the observations themselves):
  * ARP: one MAC answering for many addresses AT THE SAME TIME (proxy ARP / MAC translation of a repeater, RFC 826 and 1027); addresses held one
    after the other (a phone that gets a new address) are not a lender;
  * DHCP chaddr: the client's own MAC at an address where ARP shows a different one (RFC 2131), counted only if it was active when ARP showed it;
  * the locally administered bit (IEEE 802) and the virtual router MACs of VRRP (RFC 5798) and HSRP;
  * overlap in time of two MACs at one address AND a rhythm of continuous alternation (RFC 5227 conflict) against one MAC replacing another
    (A, B, A: two changes) or bursts of a repeater answering for a client.
Kinds: "normal", "lender" (answers for >= LENDER_MIN_IPS addresses at once, or two when DHCP proves clients behind it), "multi_address" (2 addresses
at once, no proof of clients: a host with two addresses), "virtual" (VRRP/HSRP, shared by design), "private" (locally administered: random MACs of
phones), "conflict" (shares an address with another MAC at the same time, in continuous alternation, neither a lender). Thresholds are constants to
tune with real data."""
from collections import Counter, defaultdict
from itertools import chain, combinations, product

LENDER_MIN_IPS = 3           # decision 1: three addresses (or a proof) before a MAC is called a lender
CONFLICT_MIN_SEEN = 3        # without sessions: both MACs seen at least this many times at the address
CONFLICT_MIN_OVERLAP_S = 60  # their periods overlap at least this long (a replaced device does not overlap)
CONFLICT_MIN_FLIPS = 6       # with flips: the MAC answering the address changed at least this many times between the two
CONFLICT_MAX_MEDIAN_GAP_S = 900   # ... in a continuous rhythm (median time between two changes), not in rare bursts
FLIP_MAX_GAP_S = 600         # a change after a longer silence of the address is a MAC coming back (or a replacement), not part of an alternation
PROOF_SLACK_S = 600          # a DHCP proof counts if it was active within this slack of the ARP session it explains

_VIRTUAL_PREFIXES = ("00:00:5E:00:01:", "00:00:5E:00:02:", "00:00:0C:07:AC:", "00:00:0C:9F:F")   # VRRP v4/v6, HSRP v1/v2


def is_locally_administered(mac: str) -> bool:
    try:
        return bool(int(mac[:2], 16) & 0x02)
    except ValueError:
        return False


def is_virtual(mac: str) -> bool:
    return mac.upper().startswith(_VIRTUAL_PREFIXES)


def max_simultaneous(sessions: list[tuple[float, float, str]]) -> int:
    """Most distinct addresses with an ARP session open at the same instant. sessions: [(start, end, ip)]."""
    events = sorted([(s, 0, ip) for s, e, ip in sessions] + [(e, 1, ip) for s, e, ip in sessions])      # opens before closes at the same instant
    open_ips: Counter = Counter()
    best = 0
    for _, closing, ip in events:
        if closing:
            open_ips[ip] -= 1
            if open_ips[ip] <= 0:
                del open_ips[ip]
        else:
            open_ips[ip] += 1
            best = max(best, len(open_ips))
    return best


def classify(rows: list[dict], sessions: list[dict] | None = None, flips: list[dict] | None = None) -> dict:
    """{"macs": {mac: {"kind", "ips", "behind"}}, "conflicts": [{"ip", "macs"}], "clients": {ip: dhcp_mac}}.
    `behind` of a lender: the DHCP MACs seen at its addresses while it answered there (the clients that really sit there)."""
    dhcp_at, out, by_ip, arp_sess = _classify_mac_kinds(rows, sessions)
    conflicts, maybe = _find_address_conflicts(flips, sessions, by_ip, arp_sess, out)
    return _build_classification(conflicts, out, maybe, dhcp_at)


def _classify_mac_kinds(rows, sessions):
    by_mac, by_ip = _group(rows)
    arp_sess, arp_at, dhcp_sessions = _index_sessions(sessions)
    dhcp_at = _dhcp_macs_at(by_ip)
    out: dict[str, dict] = {}
    for mac, ips in by_mac.items():
        arp_ips = sorted(ip for ip, rs in ips.items() if any(r["source"] == "arp" for r in rs))
        simultaneous, behind = _simultaneous_and_behind(mac, arp_ips, sessions, arp_sess, arp_at, dhcp_sessions, dhcp_at)
        kind = _kind(mac, simultaneous, behind)
        out[mac] = {"kind": kind, "ips": sorted(ips), "behind": behind if kind == "lender" else []}
    return dhcp_at, out, by_ip, arp_sess


def _group(rows):
    by_mac: dict[str, dict[str, list]] = {}
    by_ip: dict[str, dict[str, list]] = {}
    for r in rows:
        by_mac.setdefault(r["mac"], {}).setdefault(r["ip"], []).append(r)
        by_ip.setdefault(r["ip"], {}).setdefault(r["mac"], []).append(r)
    return by_mac, by_ip


def _index_sessions(sessions):
    arp_sess: dict[str, list] = defaultdict(list)        # mac -> [(start, end, ip)]
    arp_at: dict[tuple, list] = defaultdict(list)        # (mac, ip) -> [(start, end)]
    dhcp_at: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))      # ip -> mac -> [(start, end)]
    for s in sessions or []:
        if s["source"] == "arp":
            arp_sess[s["mac"]].append((s["start"], s["end"], s["ip"]))
            arp_at[(s["mac"], s["ip"])].append((s["start"], s["end"]))
        elif s["source"] == "dhcp":
            dhcp_at[s["ip"]][s["mac"]].append((s["start"], s["end"]))
    return arp_sess, arp_at, dhcp_at


def _kind(mac, simultaneous, behind):
    if is_virtual(mac):
        return "virtual"
    if simultaneous >= LENDER_MIN_IPS or (simultaneous >= 2 and behind):
        return "lender"
    if simultaneous == 2:
        return "multi_address"
    return "private" if is_locally_administered(mac) else "normal"


def _dhcp_macs_at(by_ip):
    """DHCP says who really is at an address (the client's own MAC, whatever ARP shows)."""
    return {ip: {m for m, rs in macs.items() if any(r["source"] == "dhcp" for r in rs)} for ip, macs in by_ip.items()}


def _simultaneous_and_behind(mac, arp_ips, sessions, arp_sess, arp_at, dhcp_sessions, dhcp_at):
    """(how many addresses the MAC answers at once, the DHCP MACs behind it): from the sessions when there are, else from the rows."""
    if sessions and mac in arp_sess:
        return max_simultaneous(arp_sess[mac]), _behind_timed(mac, arp_ips, arp_at, dhcp_sessions)
    return len(arp_ips), sorted(set(chain.from_iterable(dhcp_at.get(ip, set()) for ip in arp_ips)) - {mac})


def _behind_timed(mac, arp_ips, arp_at, dhcp_sessions):
    """DHCP MACs active at an address while `mac` answered there."""
    behind = set()
    for ip in arp_ips:
        for c, spans in dhcp_sessions.get(ip, {}).items():
            # a DHCP proof is usually a single instant (start == end): it counts when it falls within the slack of the ARP session
            if c != mac and any(max(s0 - e1, s1 - e0) <= PROOF_SLACK_S for (s0, e0), (s1, e1) in product(spans, arp_at.get((mac, ip), []))):
                behind.add(c)
    return sorted(behind)


def _find_address_conflicts(flips, sessions, by_ip, arp_sess, out):
    flips_by_ip = _flips_by_ip(flips)
    use_time = bool(sessions) and flips is not None
    conflicts, maybe = [], []
    for ip, macs in by_ip.items():
        arp_macs = {m: [r for r in rs if r["source"] == "arp"] for m, rs in macs.items()}
        for a, b in combinations(_contesting_macs(arp_macs, out), 2):
            if _contest(ip, a, b, arp_macs[a], arp_macs[b], arp_sess, flips_by_ip, use_time):
                # a "multi_address" MAC may be a repeater we cannot prove (no DHCP seen): then the contest is only possible, not certain
                sure = "multi_address" not in (out[a]["kind"], out[b]["kind"])
                (conflicts if sure else maybe).append({"ip": ip, "macs": [a, b]})
    return conflicts, maybe


def _contest(ip, a, b, rows_a, rows_b, arp_sess, flips_by_ip, use_time):
    """Do MAC a and MAC b contest address ip? With sessions and flips: overlapping, in continuous alternation; else the coarse rule."""
    if use_time:
        return _contest_timed(ip, a, b, arp_sess, flips_by_ip)
    return _contest_coarse(rows_a, rows_b)


def _contest_timed(ip, a, b, arp_sess, flips_by_ip):
    """With sessions and flips: the two MACs overlap at the address and the address changes hands between them in a continuous rhythm."""
    both = _pair_flips(ip, a, b, flips_by_ip)
    median = _median_gap(both)
    ov = _overlap_at(ip, a, b, arp_sess)
    return len(both) >= CONFLICT_MIN_FLIPS and median <= CONFLICT_MAX_MEDIAN_GAP_S and ov >= CONFLICT_MIN_OVERLAP_S


def _pair_flips(ip, a, b, flips_by_ip):
    """The changes of the MAC answering the address that went from one of the two MACs to the other (after a silence of at most FLIP_MAX_GAP_S), in time order."""
    return sorted((f for f in flips_by_ip.get(ip, []) if {f["old"], f["new"]} == {a, b} and f.get("gap", 0) <= FLIP_MAX_GAP_S), key=lambda f: f["ts"])


def _median_gap(flips):
    """Median time between two consecutive flips (the upper one for an even number of gaps); infinite when there are fewer than two flips."""
    gaps = sorted(y["ts"] - x["ts"] for x, y in zip(flips, flips[1:]))
    return gaps[len(gaps) // 2] if gaps else float("inf")


def _overlap_at(ip, a, b, arp_sess):
    """Seconds the ARP sessions of the two MACs overlap at that address."""
    return _overlap([(s, e) for s, e, i in arp_sess[a] if i == ip], [(s, e) for s, e, i in arp_sess[b] if i == ip])


def _overlap(a_sessions, b_sessions) -> float:
    return sum((max(0.0, min(e0, e1) - max(s0, s1)) for (s0, e0), (s1, e1) in product(a_sessions, b_sessions)), 0.0)


def _contest_coarse(rows_a, rows_b):
    """Without sessions: both MACs seen often enough at the address, their periods overlapping long enough."""
    (a0, a1, an), (b0, b1, bn) = _span(rows_a), _span(rows_b)
    return min(an, bn) >= CONFLICT_MIN_SEEN and min(a1, b1) - max(a0, b0) >= CONFLICT_MIN_OVERLAP_S


def _span(rs):
    return min(r["first_seen"] for r in rs), max(r["last_seen"] for r in rs), sum(r["seen_count"] for r in rs)


def _flips_by_ip(flips):
    by_ip: dict[str, list] = defaultdict(list)
    for f in flips or []:
        by_ip[f["ip"]].append(f)
    return by_ip


def _contesting_macs(arp_macs, out):
    """The MACs that answer ARP at an address and are neither lenders nor virtual: the ones that can contest it."""
    return sorted(m for m, rs in arp_macs.items() if rs and out[m]["kind"] not in ("lender", "virtual"))


def _build_classification(conflicts, out, maybe, dhcp_at) -> dict:
    for c in conflicts:
        for m in c["macs"]:
            out[m]["kind"] = "conflict"
    return {"macs": out, "conflicts": sorted(conflicts, key=lambda c: c["ip"]), "possible_conflicts": sorted(maybe, key=lambda c: c["ip"]),
            "clients": {ip: sorted(ms)[0] for ip, ms in dhcp_at.items() if len(ms) == 1}}
