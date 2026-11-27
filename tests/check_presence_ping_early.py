# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The ping behind the router starts with the adapter when the card's port was closed at its last check (decision A of 16/11): a check waits for
the slower of the two, not their sum. An offline card behind the router used to cost the adapter's timeout and then the ping's (the median
check went from 6.9 s to 8.8 s on the debug copy). Remembered only for cards behind the router that may be touched and whose adapter is not the
ping; the early ping is cancelled when the adapter answers; never on the home network.
    python tests/check_presence_ping_early.py"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import presence  # noqa: E402

ROUTED = {"10.0.20.1", "10.0.20.2"}
STEP = 0.3
pings = []


async def fake_ping(ip, port=80):
    pings.append(ip)
    await asyncio.sleep(STEP)
    return {"online": True, "mac": None}


async def same(result, device, ip, arp_task):
    return result


presence.registry.through_router = lambda ip: ip in ROUTED
presence.touch_policy.may_touch = lambda device: not device.get("no_touch")
presence.touch_policy.adapter_of = lambda device: device.get("adapter", "generic")
presence.ping.probe = fake_ping
presence.complete_with_arp = same


def check(device, ip, port_open):
    """One check as probe._probe_device_gather does it: early ping, adapter (STEP seconds), then complete."""
    async def run():
        early = presence.start_ping(device, ip)
        await asyncio.sleep(STEP)
        return await presence.complete({"online": port_open}, device, ip, None, early), early
    pings.clear()
    t = time.monotonic()
    out, early = asyncio.run(run())
    return out, early, time.monotonic() - t


dev = {"adapter": "generic"}

# 1) first check, port closed: no early ping (nothing known yet), the ping after the adapter: the sum of the two
out, early, took = check(dev, "10.0.20.1", False)
assert out["online"] and early is None and pings == ["10.0.20.1"] and took >= 2 * STEP * 0.9, (out, early, pings, took)

# 2) second check, port still closed: the ping ran with the adapter, one ping only, about one step
out, early, took = check(dev, "10.0.20.1", False)
assert out["online"] and early is not None and pings == ["10.0.20.1"] and took < 1.6 * STEP, (out, pings, took)

# 3) the port opens: the early ping is cancelled, online by the adapter, and the card is forgotten
out, early, took = check(dev, "10.0.20.1", True)
assert out["online"] and early.cancelled(), (out, early)
assert presence.start_ping(dev, "10.0.20.1") is None

# 4) the home network: never an early ping, never a ping
for _ in range(2):
    out, early, took = check(dev, "10.0.0.5", False)
    assert early is None and pings == [] and not out["online"], (early, pings)

# 5) a card that may not be touched, or with the ping adapter: never remembered
for d in ({"no_touch": True}, {"adapter": "ping"}):
    for _ in range(2):
        out, early, took = check(d, "10.0.20.2", False)
        assert early is None and pings == [], (d, early, pings)

print("check_presence_ping_early: ok")
