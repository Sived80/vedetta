"""The single MAC verdict as the rest of the app reads it (1.0 step P2): what kind of MAC each one is (macclassify, over the last days of ip_mac).

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
