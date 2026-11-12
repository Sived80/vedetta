"""An answer to ARP at an address counts as the presence of a card only when the MAC that answers may be the card's (scan/presence.py, 1.0 step P5).
Case of the field: a PC took the address of a phone that had left; the phone's card stayed online because someone answered at its address.
  - a linked card (its link may be used: linkview) is online by its own MAC; a repeater's lent MAC keeps the rule of before; another MAC never;
  - a card without a usable link: online when somebody answers, unless the MAC that answers is the usable link of ANOTHER card (one guard,
    decision 3A of 12/11; the old guard on the last MAC seen and the count of addresses per MAC are gone)."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import macverdict  # noqa: E402
from app.scan import presence  # noqa: E402

PC, PHONE, REPEATER = "74:04:F1:CC:33:7D", "AA:BB:CC:00:00:01", "AA:BB:CC:00:00:99"
arp = {"10.0.0.116": {"mac": PC.lower()}, "10.0.0.50": {"mac": "11:22:33:44:55:66"}, "10.0.0.60": {"mac": REPEATER},
       "10.0.0.70": {"mac": "11:22:33:44:55:77", "also": [PHONE.lower()]}}
assert not hasattr(presence, "answered_by_other_card") and not hasattr(presence, "mac_view") and not hasattr(presence, "owners")
macverdict.refresh({REPEATER: "lender"})


async def view(a):
    return a


def task_run(result, device, ip, table=arp):
    async def go():
        return await presence.complete_with_arp(result, device, ip, asyncio.ensure_future(view(table)))
    return asyncio.run(go())


phone = {"id": "phone", "ip": "10.0.0.116", "last_mac": PHONE, "link": PHONE, "links_of_others": frozenset({PC.lower()})}
pc = {"id": "pc", "ip": "10.0.0.117", "last_mac": PC, "link": PC, "links_of_others": frozenset({PHONE.lower()})}
plain = {"id": "tv", "ip": "10.0.0.116", "last_mac": None, "link": None, "links_of_others": frozenset({PC.lower(), PHONE.lower()})}

# --- a linked card: the PC answers at the phone's address -> not the phone, not even if the adapter found something there
assert task_run({"online": False}, phone, "10.0.0.116") == {"online": False}
assert task_run({"online": True, "x": 1}, phone, "10.0.0.116") == {"online": False}
# its own MAC at its address: online with it (also when it is the second answer of a double one)
assert task_run({"online": False}, {**phone, "ip": "10.0.0.70"}, "10.0.0.70") == {"online": True, "mac": PHONE}
assert task_run({"online": False}, {**pc, "ip": "10.0.0.116"}, "10.0.0.116") == {"online": True, "mac": PC.lower()}
# a repeater lending its MAC answers for the client behind it: the rule of before (online, with the repeater's MAC)
assert task_run({"online": False}, {**phone, "ip": "10.0.0.60"}, "10.0.0.60") == {"online": True, "mac": REPEATER}
# a MAC nobody has: not the phone either (its own MAC is known)
assert task_run({"online": False}, {**phone, "ip": "10.0.0.50"}, "10.0.0.50") == {"online": False}
# nobody answers, or no view: the adapter decides, as before
assert task_run({"online": False}, phone, "10.0.0.9") == {"online": False}
assert task_run({"online": True, "latency_ms": 3}, phone, "10.0.0.9") == {"online": True, "latency_ms": 3}
res = {"online": False}
assert asyncio.run(presence.complete_with_arp(res, phone, "10.0.0.116", None)) is res

# --- a card without a usable link: the one guard, "another card's link never keeps this one online"
assert task_run({"online": False}, plain, "10.0.0.116") == {"online": False}                         # the PC is another card's link
assert task_run({"online": True}, plain, "10.0.0.116") == {"online": False}
assert task_run({"online": False}, {**plain, "ip": "10.0.0.50"}, "10.0.0.50") == {"online": True, "mac": "11:22:33:44:55:66"}   # a MAC nobody has
assert task_run({"online": False}, {**plain, "links_of_others": frozenset()}, "10.0.0.116") == {"online": True, "mac": PC.lower()}  # no links: as before
assert task_run({"online": False}, {"id": "old", "ip": "10.0.0.116"}, "10.0.0.116") == {"online": True, "mac": PC.lower()}       # nothing told: as before
print("TUTTO OK")
