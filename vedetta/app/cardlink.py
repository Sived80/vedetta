"""The card -> MAC link (1.0 step P4): which MAC identifies a card, and on which network that MAC is seen. Pure: everything comes in as arguments
(the cards, the facts of the MAC layer, the links stored so far); nothing is read or written here. The only imports are two pure modules of the
app: macclassify (its constants) and recognition/same_device (the one judgement of "are these two MACs the same device?").

Written in the shadow: nobody reads the link to decide anything yet (step P5 will). One prudent rule makes every link, the same for the cards of
an installation that upgrades (at the first cycle, source "seed") and for the cards added later (source "rule"). A card is linked to MAC M when
  L1 it has a seq and an address on the line of a direct network now (the caller gives that network, None otherwise);
  L2 in the window of the verdict exactly one MAC answered ARP at its address, lent and virtual MACs left out: that MAC is M;
  L3 M is "normal" or "private" in the verdict;
  L4 in the last 7 days (decision 3B of 12/11) the card's history saw no other MAC that is not lent (a MAC without verdict counts as another);
  L5 no other card has M, as a link or as a candidate of this cycle;
  L6 DHCP does not prove another device at the address while M answered;
  L7 the card's automatic name, when it has one, was announced by M (name_mac);
  L8 M answered the address for at least MIN_ANSWER_S, and the MAC layer has at least that much data;
  L9 the name check of 3B: when an older MAC (up to 90 days) was behind the card, the card's name must not say it was that one: the link is refused
     when the name is announced by the older MAC and not by M, or when same_device.judge (policy notify, the one of the notice "another device
     behind the card") calls the two different devices and the name is not M's own.
Every "no" has a code (UNLINKED). A link that exists is never moved to another MAC (decision 4A): it is deleted when its card is gone (or the id
now belongs to another card: another seq), held while M names no single device or the card is off that network, and linked again when the cause
goes. Another MAC taking the card's address does not touch it: that is the case P5 must fix."""
from . import macclassify
from .recognition import same_device

MIN_ANSWER_S = 300        # two full sweeps of the network (arpview.FULL_SWEEP_S): before that a repeater may not be recognised yet
LINKABLE = ("normal", "private")
SHARED = ("lender", "virtual")
HOLD_KINDS = ("lender", "virtual", "multi_address", "conflict")
UNLINKED = ("no_seq", "off_link", "no_answer", "several_macs", "shared_kind", "history_mixed", "mac_on_two_cards", "dhcp_other", "name_other",
            "too_soon")


def _key(mac) -> str:
    return str(mac or "").strip().upper().replace("-", ":")


def judge(cards: list[dict], facts: dict, links: dict, now: float, seeding: bool = False) -> dict:
    """{"write": rows new or changed, "delete": device ids whose row goes, "unlinked": device id -> code}. cards: {id, seq, ip, network, name,
    name_mac}; facts: {kinds: MAC -> kind, sessions: the window's sessions, history: device id -> {recent, older} MAC sets, profiles: MAC ->
    same_device profile, roles: MACs of a network role}; links: device id -> stored row."""
    by_id = {c["id"]: c for c in cards}
    kept, delete = _still_theirs(links, by_id)
    write = _kept_rows(kept, by_id, facts["kinds"], now)
    candidates, unlinked = _candidates([c for c in cards if c["id"] not in links], facts, now)
    taken = {(row["network"], row["mac"]) for row in kept.values()}
    write += _new_rows(candidates, taken, unlinked, now, "seed" if seeding else "rule")
    return {"write": write, "delete": delete, "unlinked": unlinked}


def _still_theirs(links: dict, by_id: dict) -> tuple[dict, list]:
    """(the links whose card is still there with the same seq, the device ids of the others, sorted)."""
    delete = sorted(d for d, row in links.items() if d not in by_id or by_id[d].get("seq") != row["seq"])
    return {d: row for d, row in links.items() if d not in delete}, delete


def _kept_rows(kept: dict, by_id: dict, kinds: dict, now: float) -> list[dict]:
    rows = (_kept_row(row, by_id[d], kinds, now) for d, row in kept.items())
    return [r for r in rows if r]


def _kept_row(row: dict, card: dict, kinds: dict, now: float) -> dict | None:
    """The row of a link that stays, when its state changes (None otherwise): held while M names no single device or the card is off its network."""
    reason = _hold_reason(row, card, kinds)
    state = "held" if reason else "linked"
    if (state, reason) == (row["state"], row["reason"]):
        return None
    return {**row, "state": state, "reason": reason, "changed": now}


def _hold_reason(row: dict, card: dict, kinds: dict) -> str | None:
    if card.get("network") != row["network"]:
        return "network"
    kind = kinds.get(row["mac"])
    return kind if kind in HOLD_KINDS else None


def _candidates(cards: list[dict], facts: dict, now: float) -> tuple[dict, dict]:
    """(device id -> (card, M) for the cards that pass L1-L4 and L6-L9, device id -> code for the others)."""
    index = _Index(facts["sessions"], facts["kinds"])
    found, unlinked = {}, {}
    for c in cards:
        mac, code = _candidate(c, facts, index, now)
        if code:
            unlinked[c["id"]] = code
        else:
            found[c["id"]] = (c, mac)
    return found, unlinked


def _new_rows(candidates: dict, taken: set, unlinked: dict, now: float, source: str) -> list[dict]:
    """L5: a candidate MAC that another card has, or that two candidates share, links nobody."""
    pairs = [(c["network"], mac) for c, mac in candidates.values()]
    rows = []
    for device_id, (c, mac) in candidates.items():
        if (c["network"], mac) in taken or pairs.count((c["network"], mac)) > 1:
            unlinked[device_id] = "mac_on_two_cards"
            continue
        rows.append({"device_id": device_id, "seq": c["seq"], "network": c["network"], "mac": mac, "state": "linked", "reason": None,
                     "source": source, "ip": c["ip"], "since": now, "changed": now})
    return rows


class _Index:
    """The window's sessions by address: who answered ARP (and for how long), and who DHCP saw."""

    def __init__(self, sessions: list[dict], kinds: dict):
        self.kinds = kinds
        self.arp: dict[str, dict[str, list]] = {}
        self.dhcp: dict[str, dict[str, list]] = {}
        self.start = min((s["start"] for s in sessions), default=None)
        for s in sessions:
            table = self.arp if s["source"] in macclassify.ANSWER_SOURCES else self.dhcp if s["source"] == "dhcp" else None
            if table is not None:
                table.setdefault(s["ip"], {}).setdefault(_key(s["mac"]), []).append((s["start"], s["end"]))

    def answers(self, ip: str) -> tuple[list[str], bool]:
        """(the MACs that answered the address, lent and virtual ones left out; whether a lent or virtual one answered)."""
        macs = self.arp.get(ip, {})
        own = sorted(m for m in macs if self.kinds.get(m) not in SHARED)
        return own, len(own) < len(macs)

    def answered_s(self, ip: str, mac: str) -> float:
        return sum(e - s for s, e in self.arp.get(ip, {}).get(mac, []))

    def dhcp_other(self, ip: str, mac: str) -> bool:
        """A DHCP client other than `mac` active at the address within macclassify.PROOF_SLACK_S of an ARP answer of `mac` there (the judge's proof)."""
        spans = self.arp.get(ip, {}).get(mac, [])
        return any(max(s0 - e1, s1 - e0) <= macclassify.PROOF_SLACK_S
                   for other, proofs in self.dhcp.get(ip, {}).items() if other != mac for s0, e0 in proofs for s1, e1 in spans)


def _candidate(c: dict, facts: dict, index: _Index, now: float) -> tuple[str | None, str | None]:
    """(M, None) when the card passes L1-L4 and L6-L9, else (None, code)."""
    if c.get("seq") is None:
        return None, "no_seq"
    if not c.get("ip") or not c.get("network"):
        return None, "off_link"
    mac, code = _the_answer(c["ip"], index)
    if code:
        return None, code
    for check in (_check_kind, _check_time, _check_dhcp, _check_recent, _check_name_mac, _check_older):
        code = check(c, mac, facts, index, now)
        if code:
            return None, code
    return mac, None


def _the_answer(ip: str, index: _Index) -> tuple[str | None, str | None]:
    """L2: the one MAC that answered the address."""
    own, lent = index.answers(ip)
    if not own:
        return None, "shared_kind" if lent else "no_answer"
    if len(own) > 1:
        return None, "several_macs"
    return own[0], None


def _check_kind(c, mac, facts, index, now):
    return None if facts["kinds"].get(mac) in LINKABLE else "shared_kind"


def _check_time(c, mac, facts, index, now):
    if index.answered_s(c["ip"], mac) < MIN_ANSWER_S or index.start is None or now - index.start < MIN_ANSWER_S:
        return "too_soon"
    return None


def _check_dhcp(c, mac, facts, index, now):
    return "dhcp_other" if index.dhcp_other(c["ip"], mac) else None


def _others(macs, mac: str, kinds: dict) -> set[str]:
    """The MACs of a history that are neither M nor lent nor virtual (a MAC without verdict counts)."""
    return {m for m in map(_key, macs or ()) if m != mac and kinds.get(m) not in SHARED}


def _check_recent(c, mac, facts, index, now):
    """L4: the last 7 days of the card's history saw M alone."""
    return "history_mixed" if _others(facts["history"].get(c["id"], {}).get("recent"), mac, facts["kinds"]) else None


def _check_name_mac(c, mac, facts, index, now):
    """L7: the automatic name of the card was announced by M."""
    return "name_other" if c.get("name_mac") and _key(c["name_mac"]) != mac else None


def _check_older(c, mac, facts, index, now):
    """L9, the name check of decision 3B, on the MACs behind the card before the last 7 days."""
    older = _others(facts["history"].get(c["id"], {}).get("older"), mac, facts["kinds"])
    profiles = facts["profiles"]
    if not older or _announces(profiles.get(mac), c.get("name")):
        return None
    if any(_announces(profiles.get(o), c.get("name")) for o in older):
        return "name_other"
    return "name_other" if any(_different(profiles.get(o), profiles.get(mac), facts) for o in older) else None


def _announces(profile: dict | None, name: str | None) -> bool:
    """The card's name is one the MAC announces itself: its DHCP or Bonjour name, or the name of its Home Assistant device."""
    name = (name or "").strip().lower()
    if not profile or not name:
        return False
    ha = profile.get("ha") or (None, None, None)
    return name in {profile.get("dhcp_name"), profile.get("mdns_name"), (ha[2] or "").strip().lower() or None}


def _different(old: dict | None, new: dict | None, facts: dict) -> bool:
    """same_device.judge, policy notify, with its vetoes (a lent or virtual MAC, a network role, a private MAC): "different" or not."""
    if not old or not new:
        return False
    shared = {p["mac"] for m, p in facts["profiles"].items() if facts["kinds"].get(m) in SHARED}
    roles = {_key(m) for m in facts["roles"]}
    verdict = same_device.judge(old, new, shared, _key(old["mac"]) in roles, _key(new["mac"]) in roles, policy=same_device.NOTIFY)
    return verdict["verdict"] == "different"
