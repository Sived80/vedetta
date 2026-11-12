"""The presence of a linked card by its MAC (1.0 step P5). Pure: no imports from the app; the answers of the network and the tests come in as
arguments. A card whose link may be used (linkview) is online when ITS MAC answers, at whatever address:
  at its address: its MAC -> online; a lent or virtual MAC (a repeater answering for the clients behind it) -> the rule of before (online by
  whoever answers); another MAC -> not this card (a miss: the tolerance applies); nobody -> the adapter decides, as before;
  elsewhere, in the answers of THIS cycle only: its MAC at exactly one address, alone -> online there, and the card follows it at the end of the
  cycle; at two addresses or in a double answer -> nowhere (the verdict will call it multi_address or a conflict, and the link is not used).
The plan of the moves (follow) keeps every address on one card: an exchange or a chain of cards is one permutation, written at once."""
from collections import Counter


def _key(mac) -> str:
    return str(mac or "").strip().lower().replace("-", ":")


def _macs(host: dict | None) -> list[str]:
    """The MACs that answered one address: the first answer, then the others of a double answer ("also")."""
    host = host or {}
    return [m for m in map(_key, [host.get("mac"), *(host.get("also") or ())]) if m]


def at_address(link: str, host: dict | None, lent) -> str:
    """What the answer at the card's address says: "mine" (its MAC is among those that answered), "lent" (a MAC lent(mac) calls lent or
    virtual answered first), "other" (another MAC), "none" (nobody)."""
    macs = _macs(host)
    if not macs:
        return "none"
    if _key(link) in macs:
        return "mine"
    return "lent" if lent(macs[0]) else "other"


def elsewhere(link: str, answers: dict[str, dict]) -> str | None:
    """The one address where the card's MAC answered in this cycle (`answers`: address -> host, only the answers of this cycle), alone there;
    None when it was not heard, or was heard at two addresses or more, or together with another MAC."""
    mac = _key(link)
    where = [ip for ip, host in answers.items() if mac in _macs(host)]
    if len(where) != 1 or _macs(answers[where[0]]) != [mac]:
        return None
    return where[0]


def follow(cards: dict[str, str], moves: dict[str, str], allowed) -> dict[str, str]:
    """The new address of every card that changes (F1-F4): `cards` id -> address now, `moves` id -> the address where its MAC alone answered.
    A move goes ahead when the card may take that address (allowed(id, address): the same network, on the line, not paused) and no other card
    wants it. A card that holds the address and does not move takes the address left free at the end of the chain (an exchange when two cards
    swap). The result keeps every address on one card."""
    go = _going(cards, moves, allowed)
    holder = {ip: cid for cid, ip in cards.items()}
    target = {ip: cid for cid, ip in go.items()}
    plan = dict(go)
    for cid, ip in go.items():
        stays = holder.get(ip)
        if stays is not None and stays not in go:
            plan[stays] = _left_free(cards[cid], target, cards)
    return plan


def _going(cards: dict[str, str], moves: dict[str, str], allowed) -> dict[str, str]:
    """The moves that go ahead: a card that changes address, to an address no other card wants and that it may take."""
    wanted = Counter(moves.values())
    return {cid: ip for cid, ip in moves.items() if cid in cards and ip != cards[cid] and wanted[ip] == 1 and allowed(cid, ip)}


def _left_free(ip: str, target: dict[str, str], cards: dict[str, str]) -> str:
    """The end of the chain that starts at the address a moving card leaves: while another moving card takes it, the address that one leaves."""
    for _ in range(len(cards) + 1):
        if ip not in target:
            return ip
        ip = cards[target[ip]]
    raise ValueError("a chain of moves that never ends")      # cannot happen: each address has one card and one card that wants it
