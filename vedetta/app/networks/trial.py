# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""«Try and add»: a network the person is about to write, tried before it is saved (POST /api/networks/test). Every address of it (the excluded
ranges never) gets one ping, a few at a time; the answer says how many answered, the first few, and what Vedetta would see of it function by
function (the judge of the list, panel.describe, with «it answers» from this sweep). Nothing is written. The ping is given by the caller (the
question of the ping adapter, K1: no port, no name request), so this module stays below the searches."""
import asyncio

from . import panel
from .model import Network

AT_ONCE = 64          # pings in flight together: a /22 takes about 16 rounds of the ping timeout
SAMPLE = 5            # addresses that answered, shown by the page


async def sweep(network: Network, ping) -> tuple:
    """(the addresses asked, those that answered) in the order of the network. ping(ip) is true when the address answered."""
    hosts = [h for h in network.cidr.hosts() if network.holds(h)]
    gate = asyncio.Semaphore(AT_ONCE)

    async def one(host) -> bool:
        async with gate:
            return bool(await ping(str(host)))

    answered = await asyncio.gather(*(one(h) for h in hosts))
    return [str(h) for h in hosts], [str(h) for h, ok in zip(hosts, answered) if ok]


def outcome(network: Network, seen: panel.Seen, asked: list, answering: list) -> dict:
    """The answer of the try: {"cidr", "asked", "answer", "sample", "vlan", "caps"}."""
    described = panel.describe(network, seen, network.name, False, answers=bool(answering))
    return {"cidr": str(network.cidr), "asked": len(asked), "answer": len(answering), "sample": answering[:SAMPLE],
            "vlan": described["vlan"], "caps": described["caps"]}
