"""Presence of a card behind the router (decision A of 15/11): the adapter asks the card's port, and on the home network ARP saves a device with
that port closed; through the router ARP never answers, so a UniFi without port 80, Home Assistant on 8123 or a LED strip with no open port stayed
offline for ever while they answered the ping of P11. complete_with_ping asks one ICMP echo when the card is behind the router and the adapter
said offline; never on the home network, never when the adapter already said online, never when the card may not be touched, never twice (the
ping adapter already asked it). The MAC stays unknown (ARP does not cross the router).
    python tests/check_presence_routed_ping.py"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan.presence import complete_with_ping  # noqa: E402

asked = []


def answers(online: bool):
    async def ask(ip, port=80):
        asked.append(ip)
        return {"online": online, "mac": None}
    return ask


def run(result, routed, online=True, touch=True, adapter="generic"):
    asked.clear()
    return asyncio.run(complete_with_ping(result, "10.0.20.1", routed=routed, may_touch=touch, adapter=adapter, ask=answers(online)))


# 1) behind the router, port closed, the ping answers: online, no MAC, one question
out = run({"online": False, "mac": None}, routed=True)
assert out == {"online": True, "mac": None}, out
assert asked == ["10.0.20.1"], asked

# 2) behind the router, the ping does not answer either: offline, the same result
res = {"online": False}
out = run(res, routed=True, online=False)
assert out == {"online": False} and asked == ["10.0.20.1"], (out, asked)

# 3) the adapter already said online: nothing asked, the same object (its data kept)
res = {"online": True, "mac": None, "uptime": 5}
assert run(res, routed=True) is res and asked == []

# 4) the home network: never (ARP is the safety net there)
res = {"online": False}
assert run(res, routed=False) is res and asked == []

# 5) a card that may not be touched, or whose adapter is already the ping: never
assert run({"online": False}, routed=True, touch=False) == {"online": False} and asked == []
assert run({"online": False}, routed=True, adapter="ping") == {"online": False} and asked == []

# 6) the adapter result without "mac" stays without it: only "online" changes
out = run({"online": False, "extra": {"a": 1}}, routed=True)
assert out == {"online": True, "extra": {"a": 1}}, out

print("check_presence_routed_ping: ok")
