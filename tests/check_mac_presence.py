"""The presence of a linked card by its MAC (1.0 step P5, macpresence, pure). One case per line of the plan's table:
  at the card's address: its MAC -> online; a lent or virtual MAC (a repeater) -> the rule of before; another MAC -> not this card; nobody -> the
  adapter decides, as before;
  elsewhere, in the answers of THIS cycle: the MAC at exactly one address -> the card is there; at two addresses or in a double answer -> nowhere;
and the plan of the moves (F1-F5): a move to a free address, an exchange of two cards, a chain of three, a card moved onto the address of a card
that stays (it takes the address left free), two cards towards one address (none moves), an address the card may not take (none). Then a random
test over 2000 made-up networks: after the moves the addresses stay unique, a card is never present by another card's MAC, every move goes to an
address where the card's MAC answered in this cycle, and never to another network."""
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import macpresence  # noqa: E402

M1, M2, M3, REP, OTHER = "02:00:00:00:01:01", "02:00:00:00:01:02", "02:00:00:00:01:03", "02:00:00:00:01:0a", "02:00:00:00:01:0f"
lent = {REP}.__contains__

# --- at the address of the card (keys are compared without case)
assert macpresence.at_address(M1, {"mac": M1.upper()}, lent) == "mine"
assert macpresence.at_address(M1, {"mac": OTHER, "also": [M1]}, lent) == "mine"          # a double answer with M among them: M is there
assert macpresence.at_address(M1, {"mac": REP}, lent) == "lent"                          # a repeater answers for the clients behind it
assert macpresence.at_address(M1, {"mac": OTHER}, lent) == "other"
assert macpresence.at_address(M1, None, lent) == "none"
assert macpresence.at_address(M1, {}, lent) == "none"
assert macpresence.at_address(M1, {"mac": ""}, lent) == "none"

# --- elsewhere, in the answers of this cycle
answers = {"10.0.0.5": {"mac": M1}, "10.0.0.6": {"mac": M2}, "10.0.0.7": {"mac": M2}, "10.0.0.8": {"mac": OTHER, "also": [M3]}}
assert macpresence.elsewhere(M1.upper(), answers) == "10.0.0.5"
assert macpresence.elsewhere(M2, answers) is None            # two addresses: the verdict will call it multi_address or a lender
assert macpresence.elsewhere(M3, answers) is None            # a double answer (DUP): two devices claim the address
assert macpresence.elsewhere(OTHER, answers) is None         # the first of a double answer: same
assert macpresence.elsewhere(REP, answers) is None           # not seen in this cycle
assert macpresence.elsewhere(M1, {}) is None


# --- the plan of the moves: cards {id: ip}, moves {id: address where its MAC answered}, allowed(id, ip)
def everywhere(card_id, ip):
    return True


cards = {"a": "10.0.0.1", "b": "10.0.0.2", "c": "10.0.0.3", "d": "10.0.0.4"}
assert macpresence.follow(cards, {"a": "10.0.0.50"}, everywhere) == {"a": "10.0.0.50"}                       # F2 a free address
assert macpresence.follow(cards, {"a": "10.0.0.2", "b": "10.0.0.1"}, everywhere) == {"a": "10.0.0.2", "b": "10.0.0.1"}   # exchange
assert macpresence.follow(cards, {"a": "10.0.0.2", "b": "10.0.0.3", "c": "10.0.0.1"}, everywhere) == {"a": "10.0.0.2", "b": "10.0.0.3", "c": "10.0.0.1"}
assert macpresence.follow(cards, {"a": "10.0.0.2", "b": "10.0.0.9"}, everywhere) == {"a": "10.0.0.2", "b": "10.0.0.9"}  # chain to a free one
assert macpresence.follow(cards, {"a": "10.0.0.2"}, everywhere) == {"a": "10.0.0.2", "b": "10.0.0.1"}        # F3 b stays: takes the one left free
assert macpresence.follow(cards, {"a": "10.0.0.2", "c": "10.0.0.1"}, everywhere) == {"a": "10.0.0.2", "c": "10.0.0.1", "b": "10.0.0.3"}
assert macpresence.follow(cards, {"a": "10.0.0.50", "b": "10.0.0.50"}, everywhere) == {}                     # F4 two towards one: none
assert macpresence.follow(cards, {"a": "10.0.0.50", "b": "10.0.0.50", "c": "10.0.0.60"}, everywhere) == {"c": "10.0.0.60"}
assert macpresence.follow(cards, {"a": "10.0.0.50"}, lambda i, ip: False) == {}                              # F1 an address it may not take
assert macpresence.follow(cards, {"a": "10.0.0.2", "b": "10.0.0.1"}, lambda i, ip: i != "b") == {"a": "10.0.0.2", "b": "10.0.0.1"}, \
    "b may not go elsewhere on its own, but the exchange keeps it on its own network: a takes b's address, b the one left free"
assert macpresence.follow(cards, {"a": "10.0.0.1"}, everywhere) == {}                                       # already there
assert macpresence.follow({}, {}, everywhere) == {}

# --- random test: 2000 made-up networks, the whole pure path of a cycle (at the address, elsewhere, the plan of the moves)
rng = random.Random(5005)
NETS = {"main": ["10.0.0.%d" % i for i in range(1, 13)], "lab": ["10.0.9.%d" % i for i in range(1, 5)]}
net_of = {ip: n for n, ips in NETS.items() for ip in ips}
MACS = ["02:00:00:00:02:%02x" % i for i in range(14)]
moved_any = swapped_any = 0
for world in range(2000):
    ips = rng.sample(sorted(net_of), rng.randrange(1, 9))
    cards = {"c%d" % i: ip for i, ip in enumerate(ips)}
    pool = rng.sample(MACS, len(MACS))
    links = {cid: pool[i] for i, cid in enumerate(cards) if rng.random() < 0.7}      # never one MAC on two cards (the writer refuses it)
    answers = {}
    for ip in rng.sample(sorted(net_of), rng.randrange(0, 12)):
        host = {"mac": rng.choice(MACS + [REP])}
        if rng.random() < 0.1:
            host["also"] = [rng.choice(MACS)]
        answers[ip] = host
    present, moves = {}, {}
    for cid, ip in cards.items():
        link = links.get(cid)
        if link is None:
            continue
        seen = macpresence.at_address(link, answers.get(ip), lent)
        if seen == "mine":
            host = answers[ip]
            assert link in [host["mac"]] + host.get("also", []), "present only by its own MAC"
            present[cid] = ip
        elif seen in ("other", "none"):
            y = macpresence.elsewhere(link, answers)
            if y is not None:
                assert answers[y]["mac"] == link and not answers[y].get("also"), "a move goes where the card's MAC alone answered"
                moves[cid] = y
    plan = macpresence.follow(cards, moves, lambda cid, ip: net_of[ip] == net_of[cards[cid]])
    after = {**cards, **plan}
    assert len(set(after.values())) == len(after), ("the addresses stay unique", cards, moves, plan)
    for cid, ip in plan.items():
        assert net_of[ip] == net_of[cards[cid]], "never a move to another network"
        assert ip == moves.get(cid) or ip in set(cards.values()),             "a card goes where its MAC answered, or (it stays, or its own move was refused) takes the address another card left"
    assert not set(plan) & set(present), "a card present at its address never moves"
    moved_any += bool(plan)
    swapped_any += any(cid not in moves for cid in plan) or any(ip in cards.values() for cid, ip in plan.items() if cid in moves)
assert moved_any > 300 and swapped_any > 50, (moved_any, swapped_any)
print("TUTTO OK")
