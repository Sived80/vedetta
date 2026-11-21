"""Confirm before saying offline: a card on Home Assistant's own network that was online and is about to go offline (this miss reaches the
tolerance) gets ONE targeted ARP check (arp-scan of its address) and a fresh read of the neighbour table; if it answers there, as itself, it
stays online. Bounded: only the cards about to drop, at most MAX_PER_CYCLE per cycle in one arp-scan run with a short timeout; never behind the
router (the ping of the sweep stays the rule there). The ARP check and the neighbour table are fakes: no packet. Invented values only."""
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import netutil  # noqa: E402
from app.scan import presence_confirm as C, scan_arp  # noqa: E402

netutil.last_network = "192.0.2.0/24"
calls = []
ANSWER: dict = {}
NEIGH: list = []


async def fake_arp_scan(targets=None, timeout=None, interval_ms=None):
    calls.append(("arp-scan", list(targets or []), timeout, interval_ms))
    return [h for ip, h in ANSWER.items() if ip in (targets or [])]


async def fake_neighbors(net=None):
    calls.append(("neigh", net))
    return list(NEIGH)

scan_arp.arp_scan, scan_arp.neighbors = fake_arp_scan, fake_neighbors


class State:
    def __init__(self, cards, misses):
        self.devices = {c["id"]: c for c in cards}
        self._misses = misses

    @staticmethod
    def _miss_limit():
        return 3


def card(i, ip, online=True, link=None):
    return {"id": i, "ip": ip, "online": online, "link": link, "links_of_others": frozenset()}


def run(cards, misses, results):
    calls.clear()
    st = State([{k: c[k] for k in ("id", "ip", "online")} for c in cards], misses)
    out = [dict(r) for r in results]
    asyncio.run(C.confirm_before_offline(st, cards, out))
    return out


off = {"online": False}
# 1) about to drop, answers the targeted ARP: stays online with its MAC; one arp-scan, short, spaced
ANSWER.update({"192.0.2.10": {"ip": "192.0.2.10", "mac": "02:00:00:00:00:10", "vendor": None}})
out = run([card("a", "192.0.2.10")], {"a": 2}, [off])
assert out[0]["online"] and out[0]["mac"] == "02:00:00:00:00:10", out
arp_calls = [c for c in calls if c[0] == "arp-scan"]
assert arp_calls == [("arp-scan", ["192.0.2.10"], C.TIMEOUT_S, C.INTERVAL_MS)], calls

# 2) silent to the ARP check but REACHABLE in the neighbour table read right after: online
ANSWER.clear()
NEIGH[:] = [{"ip": "192.0.2.11", "mac": "02:00:00:00:00:11", "vendor": None}]
out = run([card("b", "192.0.2.11")], {"b": 2}, [off])
assert out[0]["online"], out
NEIGH.clear()

# 3) no answer anywhere: offline, as before
out = run([card("c", "192.0.2.12")], {"c": 2}, [off])
assert not out[0]["online"]

# 4) not asked: still within the tolerance, already offline, already online, behind the router
ANSWER.update({ip: {"ip": ip, "mac": "02:00:00:00:00:2%d" % n, "vendor": None} for n, ip in enumerate(["192.0.2.20", "192.0.2.21", "10.9.0.5"])})
out = run([card("d", "192.0.2.20"), card("e", "192.0.2.21", online=False), card("f", "10.9.0.5"), card("g", "192.0.2.22")],
          {"d": 0, "e": 5, "f": 2, "g": 2}, [off, off, off, {"online": True}])
assert calls == [], calls
assert [r["online"] for r in out] == [False, False, False, True]

# 5) the answer is another card's (its link): not this card, offline
ANSWER.clear()
ANSWER["192.0.2.30"] = {"ip": "192.0.2.30", "mac": "02:00:00:00:00:99", "vendor": None}
out = run([card("h", "192.0.2.30", link="02:00:00:00:00:30")], {"h": 2}, [off])
assert not out[0]["online"], out

# 6) many at once: at most MAX_PER_CYCLE addresses, in ONE arp-scan run
ANSWER.clear()
many = [card("m%d" % n, "192.0.2.%d" % (100 + n)) for n in range(C.MAX_PER_CYCLE + 20)]
run(many, {c["id"]: 2 for c in many}, [off] * len(many))
arp_calls = [c for c in calls if c[0] == "arp-scan"]
assert len(arp_calls) == 1 and len(arp_calls[0][1]) == C.MAX_PER_CYCLE, calls

# 7) the ARP check fails: nothing changes, no error
async def broken(*a, **k):
    raise RuntimeError("arp-scan missing")
scan_arp.arp_scan = broken
out = run([card("i", "192.0.2.40")], {"i": 2}, [off])
assert not out[0]["online"]
scan_arp.arp_scan = fake_arp_scan

# 8) said in the log at debug level
lines = []


class Catch(logging.Handler):
    def emit(self, record):
        lines.append((record.levelno, record.getMessage()))


log = logging.getLogger("dashboard")
log.addHandler(Catch())
log.setLevel(logging.DEBUG)
ANSWER["192.0.2.50"] = {"ip": "192.0.2.50", "mac": "02:00:00:00:00:50", "vendor": None}
run([card("j", "192.0.2.50"), card("k", "192.0.2.51")], {"j": 2, "k": 2}, [off, off])
assert any(lv == logging.DEBUG and "192.0.2.50" in m for lv, m in lines) and any(lv == logging.DEBUG and "192.0.2.51" in m for lv, m in lines), lines

# 9) the cycle asks it after the probes, before the results are applied
import inspect  # noqa: E402
from app import state_cycle  # noqa: E402
src = inspect.getsource(state_cycle.poll_once)
assert "confirm_before_offline" in src and src.index("confirm_before_offline") < src.index("_apply_results"), "the cycle does not confirm"

print("OK presence confirm")
