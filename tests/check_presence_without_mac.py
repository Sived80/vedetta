"""Characterization of presence for a card the ARP table does not know (a device behind a router never is in it), before the work on more networks:
complete_with_arp leaves the result of the adapter as it is when the address is not in the ARP view (online or offline, with or without MAC, and the dictionary itself is not
touched). A card without a usable link (a new card) is not kept online by the MAC at its address when that MAC is another card's usable link (the one
guard of 1.0 step P5, decision 3A), and is when the MAC belongs to nobody. When the address IS in the view, the answer makes the card online and gives the MAC - the rule
the work on more networks must restrict to the direct network (a router with proxy ARP answers for the others).
    python tests/check_presence_without_mac.py"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan.presence import complete_with_arp  # noqa: E402


def view(arp: dict):
    async def task():
        return arp
    return task()


card = {"id": "scan-10-0-20-30", "ip": "10.0.20.30"}
ARP = {"10.0.0.10": {"mac": "AA:BB:CC:00:00:0A"}}
run = lambda result, arp, device=card: asyncio.run(complete_with_arp(result, device, "10.0.20.30", view(arp)))  # noqa: E731

# 1) the address is not in the ARP view: the adapter's result as it is, the same object
for result in ({"online": True, "latency_ms": 12}, {"online": False}, {"online": True, "mac": "AA:BB:CC:00:00:1E"}):
    before = dict(result)
    out = run(result, ARP)
    assert out is result and out == before, (out, before)

# 2) no ARP task at all (the check of the cycle without ARP): the result as it is
res = {"online": False}
assert asyncio.run(complete_with_arp(res, card, "10.0.20.30", None)) is res

# 3) a card without a usable link: not kept online by the MAC at its address when that MAC is another card's usable link; kept by a MAC nobody has
arp = {"10.0.20.30": {"mac": "AA:BB:CC:00:00:0A"}}
assert run({"online": True}, arp, {**card, "links_of_others": frozenset({"aa:bb:cc:00:00:0a"})}) == {"online": False}
assert run({"online": False}, arp, {**card, "links_of_others": frozenset()}) == {"online": True, "mac": "AA:BB:CC:00:00:0A"}
out = run({"online": True}, {}, {**card, "links_of_others": frozenset({"aa:bb:cc:00:00:0a"})})
assert out == {"online": True}, out                       # nobody answers at the address: the adapter's result, as before

# 4) the address IS in the view (today, also when the answer is a router's proxy ARP): online, with that MAC
proxy = {"10.0.20.30": {"mac": "02:00:5E:00:00:01"}, "10.0.0.1": {"mac": "02:00:5E:00:00:01"}}
out = run({"online": False}, proxy)
assert out == {"online": True, "mac": "02:00:5E:00:00:01"}, out

print("check_presence_without_mac: ok")
