"""The single MAC verdict as the rest of the app reads it (1.0 step P2): what kind of MAC each one is (macclassify, over the last days of ip_mac),
and (step P3) which addresses are contested by two MACs right now.

maclayer fills it after it stores the verdict of a cycle (and once at start, from the last run), reading the stored table back: this module only
keeps that answer in memory, so the rules that ask about a MAC (the Bonjour memory, the clients behind a repeater) cost nothing and all get the same
one. No rule counts the addresses of a MAC by itself any more. No imports from the app: anyone may read it."""

SHARED_KINDS = frozenset({"lender", "virtual"})     # a MAC that names no single device: lent by a repeater, or shared by design (VRRP/HSRP)

_kinds: dict[str, str] = {}


def _key(mac) -> str:
    return str(mac or "").strip().upper().replace("-", ":")


def refresh(kinds: dict[str, str]) -> None:
    """The verdict just stored (MAC -> kind) becomes the one everybody reads; it replaces the last one in one step."""
    global _kinds
    _kinds = {_key(mac): kind for mac, kind in (kinds or {}).items()}


def kind(mac) -> str | None:
    """normal, private, lender, multi_address, virtual or conflict; None when the MAC has no verdict (not seen in the window, or no cycle yet)."""
    return _kinds.get(_key(mac))


def shared(mac) -> bool:
    """The MAC names no single device: what is heard at one of its addresses must not be filed under it."""
    return kind(mac) in SHARED_KINDS


def lenders() -> frozenset[str]:
    """The MACs (upper case, colons) that a repeater lends to the clients behind it."""
    return frozenset(mac for mac, k in _kinds.items() if k == "lender")


# The IP conflicts of the verdict (1.0 step P3): an address contested by two MACs, with the last evidence of the contest (macclassify.last_evidence).
# The verdict reads days of history, so a conflict that ended stays in it: here one is "going on" only while its last evidence is recent.
CONFLICT_OPEN_S = 20 * 60    # decided 12/11: over twice the longest gap seen on a real network (a relay quiet for 4 judgments = 8 min, 14 min at most)

_conflicts: list[tuple[str, tuple[str, ...], float]] = []


def refresh_conflicts(rows: list[dict]) -> None:
    """The conflicts just stored ({ip, macs, last_evidence}) become the ones everybody reads; they replace the last ones in one step."""
    global _conflicts
    _conflicts = [(r["ip"], tuple(_key(m) for m in r["macs"]), float(r["last_evidence"])) for r in rows or [] if r.get("last_evidence") is not None]


def conflicts(now: float) -> dict[str, list[str]]:
    """The conflicts going on at `now` (last evidence at most CONFLICT_OPEN_S old): address -> its MACs (upper case, colons, sorted, each once)."""
    out: dict[str, set[str]] = {}
    for ip, macs, last in _conflicts:
        if last >= now - CONFLICT_OPEN_S:
            out.setdefault(ip, set()).update(macs)
    return {ip: sorted(macs) for ip, macs in sorted(out.items())}
