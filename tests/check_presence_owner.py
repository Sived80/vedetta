"""An answer to ARP at an address counts as the presence of a card only if the MAC that answers is not positively another card's (scan/presence.py).
Case of the field: a PC took the address of a phone that had left; the phone's card stayed online because someone answered at its address."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import presence  # noqa: E402

PC, PHONE, REPEATER = "74:04:f1:cc:33:7d", "aa:bb:cc:00:00:01", "aa:bb:cc:00:00:99"
owner = {PC: "pc", PHONE: "phone", REPEATER: "rep"}
arp = {"10.0.0.116": {"mac": PC.upper()}, "10.0.0.50": {"mac": "11:22:33:44:55:66"}}
phone = {"id": "phone", "ip": "10.0.0.116", "last_mac": PHONE}

# the PC answers at the phone's address, and the PC is another card: not the phone
assert presence.answered_by_other_card(phone, "10.0.0.116", arp, owner)
# the MAC of the card itself: it is the device
assert not presence.answered_by_other_card({**phone, "last_mac": PC}, "10.0.0.116", arp, {PC: "phone"})
# a MAC nobody knows (a phone with a new private MAC at its address): not decided against the card
assert not presence.answered_by_other_card(phone, "10.0.0.50", arp, owner)
# no ARP answer, no known owners, no MAC in the answer: nothing to say
assert not presence.answered_by_other_card(phone, "10.0.0.7", arp, owner)
assert not presence.answered_by_other_card(phone, "10.0.0.116", arp, {})
assert not presence.answered_by_other_card(phone, "10.0.0.116", {"10.0.0.116": {}}, owner)
# a repeater lends its MAC to the clients behind it: the same MAC at more than one address never identifies a card
lent = {"10.0.0.116": {"mac": REPEATER}, "10.0.0.2": {"mac": REPEATER}}
assert not presence.answered_by_other_card(phone, "10.0.0.116", lent, owner)
# the map of owners: one card per MAC, a MAC claimed by two cards (or by none) is left out
assert presence.owners({"a": "AA:BB:CC:00:00:01", "b": "aa:bb:cc:00:00:02", "c": None}) == {"aa:bb:cc:00:00:01": "a", "aa:bb:cc:00:00:02": "b"}
assert presence.owners({"a": "AA:BB:CC:00:00:01", "b": "aa:bb:cc:00:00:01"}) == {}
# the step of the probe: the ARP answer completes the result, unless it is another card's
import asyncio  # noqa: E402


async def steps():
    async def view(a):
        return a
    mine = {**phone, "mac_owner": owner}
    got = await presence.complete_with_arp({"online": False}, mine, "10.0.0.116", asyncio.ensure_future(view(arp)))
    assert got == {"online": False}, got                     # the PC answers at the phone's address: the phone is not there
    got = await presence.complete_with_arp({"online": True, "x": 1}, mine, "10.0.0.116", asyncio.ensure_future(view(arp)))
    assert got == {"online": False}, got                     # not even if the adapter found something there
    got = await presence.complete_with_arp({"online": False}, mine, "10.0.0.50", asyncio.ensure_future(view(arp)))
    assert got == {"online": True, "mac": "11:22:33:44:55:66"}, got      # an unknown MAC at the address: ARP says it is there
    got = await presence.complete_with_arp({"online": False}, mine, "10.0.0.9", asyncio.ensure_future(view(arp)))
    assert got == {"online": False}, got                     # nobody answers
    got = await presence.complete_with_arp({"online": False}, mine, "10.0.0.116", None)
    assert got == {"online": False}, got                     # no ARP view


asyncio.run(steps())
print("TUTTO OK")
