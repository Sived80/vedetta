"""Golden-master test of ArpView.by_ip (the cached view of the ARP: a normal network or the plan of a large one, with its logs, timeouts and failures) and ArpView._remember (large network:
what the blocks asked now replace what was remembered, the rest is kept up to ARP_MEMORY_S, the neighbours are added, the blocks are marked, the callback is told): generated sequences
of calls on one view, with the collaborators replaced by deterministic in-memory ones (a frozen clock for time() and monotonic(), a fake scanner, a fake history, a fake logger, the
plan and the small-network sweep scripted, a callback that records or fails) and a memory/cache seeded right on the thresholds. For each sequence the returned views AND the whole final
state of the instance (cache, memory, plan info, counters...) AND the ORDER and arguments of every call must be exactly the ones stored in tests/golden/arpview.json (a digest per
sequence, plus a readable sample), written from the code as it was before the methods were split.
Regenerate only on purpose:  ARPVIEW_GOLDEN_UPDATE=1 python tests/check_arpview_golden.py"""
import asyncio
import hashlib
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import arpview  # noqa: E402
from app.arpview import ArpView  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "arpview.json"
N = 1400
rng = random.Random(86420)
LOG: list = []
CLK = {"t": 3_000_000.0, "m": 500.0}
SCRIPT: dict = {}
LOOP = asyncio.new_event_loop()


def pick(seq):
    return seq[rng.randrange(len(seq))]


def ser(x):
    """Stable form of any value: dicts keep their key order, sets are sorted, exceptions are their type."""
    if isinstance(x, dict):
        return {"d": [[ser(k), ser(v)] for k, v in x.items()]}
    if isinstance(x, (list, tuple)):
        return [ser(v) for v in x]
    if isinstance(x, (set, frozenset)):
        return {"s": sorted((ser(v) for v in x), key=json.dumps)}
    if isinstance(x, BaseException):
        return {"exc": type(x).__name__}
    if x is None or isinstance(x, (str, int, float, bool)):
        return x
    return {"obj": type(x).__name__}


class FakeTime:
    @staticmethod
    def time():
        v = CLK["t"]
        CLK["t"] += 0.25
        LOG.append(["time", v])
        return v

    @staticmethod
    def monotonic():
        v = CLK["m"]
        CLK["m"] += 0.25
        LOG.append(["mono", v])
        return v


class FakeLogger:
    def __getattr__(self, name):
        def call(fmt, *args, **kw):
            LOG.append(["log", name, fmt, ser(list(args)), ser(kw)])
        return call


def maybe_raise(key):
    v = SCRIPT.get(key)
    if isinstance(v, BaseException):
        raise v
    return v


class FakeScanner:
    @staticmethod
    async def arp_scan(targets=None, timeout=0, interval_ms=None):
        LOG.append(["arp_scan", ser(targets), timeout, interval_ms])
        return maybe_raise("hosts")

    @staticmethod
    async def neighbors(network):
        LOG.append(["neighbors", network])
        return maybe_raise("neighbors")


class FakeHistory:
    @staticmethod
    def scan_blocks_mark(found, now):
        LOG.append(["mark", ser(found), now])
        if SCRIPT.get("mark_fails"):
            raise OSError("disk")


arpview.time = FakeTime
arpview.scanner = FakeScanner
arpview.history = FakeHistory
arpview.logger = FakeLogger()

NET = "10.0.0.0/16"
BLOCKS = ["10.0.%d.0/24" % i for i in range(5)]
OUTSIDE = ["10.0.9.%d" % i for i in range(1, 4)] + ["192.168.1.5"]


def rand_ip():
    r = rng.random()
    if r < 0.8:
        return "10.0.%d.%d" % (rng.randrange(0, 6), rng.randrange(1, 5))
    return pick(OUTSIDE)


def rand_host(ip=None):
    ip = ip or rand_ip()
    return {"ip": ip, "mac": "AA:BB:CC:00:00:%02d" % rng.randrange(1, 9), "vendor": pick([None, "X"])}


def rand_hosts(maybe_bad=True):
    hosts = [rand_host() for _ in range(rng.randrange(0, 6))]
    if maybe_bad and hosts and rng.random() < 0.03:
        hosts[rng.randrange(len(hosts))] = {"mac": "AA"}
    if maybe_bad and hosts and rng.random() < 0.03:
        hosts[rng.randrange(len(hosts))]["ip"] = "not-an-ip"
    return hosts


def rand_plan():
    blocks = rng.sample(BLOCKS, rng.randrange(0, 4))
    singles = [rand_ip() for _ in range(rng.randrange(0, 3))]
    targets = blocks + singles
    if rng.random() < 0.3 and blocks:
        targets.append(blocks[0])
    plan = {"network": NET, "blocks": blocks, "targets": targets, "fresh": rng.sample(BLOCKS, rng.randrange(0, 3)),
            "total": rng.randrange(1, 60), "done": rng.randrange(0, 30)}
    r = rng.random()
    if r < 0.02:
        del plan["fresh"]
    elif r < 0.04:
        plan["targets"] = ["bad-target"]
    elif r < 0.05:
        plan["blocks"] = ["bad-block"]
    return plan


def seed_mem(view):
    """Memory entries right on the ARP_MEMORY_S threshold, a few fresh ones and a few old ones."""
    for _ in range(rng.randrange(0, 6)):
        ip = rand_ip()
        delta = pick([-0.25, 0.0, 0.25, 10.0, -10.0, -arpview.ARP_MEMORY_S * 2, 0.0])
        view.mem[ip] = (CLK["t"] - arpview.ARP_MEMORY_S + delta if delta not in (10.0, -10.0, -arpview.ARP_MEMORY_S * 2) else CLK["t"] + delta, rand_host(ip))


def run(coro):
    return LOOP.run_until_complete(coro)


def sequence():
    fresh_calls = []
    fail_cb = rng.random() < 0.05

    def on_fresh(blocks):
        LOG.append(["fresh", ser(blocks)])
        if fail_cb:
            raise RuntimeError("callback")
    view = ArpView(on_fresh)
    if rng.random() < 0.4:
        view.plan_info = {"network": NET, "total": 3, "done": 1}
    if rng.random() < 0.3:
        view.first_blocks_logged = True
    if rng.random() < 0.3:
        view.cache = (CLK["m"] - pick([0.0, 1.0, 5.0, 1000.0]), {"10.0.0.1": rand_host("10.0.0.1")})
    seed_mem(view)
    out = []
    LOG.clear()
    for _ in range(rng.randrange(1, 6)):
        if rng.random() < 0.15:
            plan = rand_plan()
            SCRIPT.clear()
            SCRIPT.update(hosts=None, neighbors=pick([rand_hosts(), rand_hosts(), RuntimeError("n"), asyncio.TimeoutError()]), mark_fails=rng.random() < 0.2)
            if rng.random() < 0.5:
                seed_mem(view)
            try:
                res = ser(run(view._remember(rand_hosts(), plan)))
            except BaseException as exc:
                res = ser(exc)
            out.append(["remember", res])
            continue
        CLK["m"] += pick([0.0, 0.0, 0.25, 1.0, 30.0, 400.0])
        max_age = pick([0, 1, 5, 60.0, 1e9])
        if view.cache is not None and rng.random() < 0.5:
            max_age = CLK["m"] - view.cache[0] + pick([0.0, 0.0, -0.25, 0.25])
        r = rng.random()
        plan = None if r < 0.35 else rand_plan()
        if rng.random() < 0.05:
            plan = pick([RuntimeError("plan"), asyncio.TimeoutError(), {}])
        small = pick([({"10.0.0.7": rand_host("10.0.0.7")}, 256), ({}, 0), ({"10.0.0.8": rand_host("10.0.0.8"), "10.0.0.9": rand_host("10.0.0.9")}, 3),
                      RuntimeError("small"), asyncio.TimeoutError()])
        SCRIPT.clear()
        SCRIPT.update(hosts=pick([rand_hosts(), rand_hosts(), rand_hosts(), RuntimeError("scan"), asyncio.TimeoutError()]),
                      neighbors=pick([rand_hosts(), rand_hosts(), RuntimeError("n"), asyncio.TimeoutError()]), mark_fails=rng.random() < 0.15)
        if rng.random() < 0.4:
            seed_mem(view)

        async def fake_plan(plan=plan):
            LOG.append(["plan"])
            if isinstance(plan, BaseException):
                raise plan
            return plan

        async def fake_small(small=small):
            LOG.append(["small"])
            if isinstance(small, BaseException):
                raise small
            return small
        view._arp_plan = fake_plan
        view._arp_small = fake_small
        try:
            res = ser(run(view.by_ip(max_age)))
        except BaseException as exc:
            res = ser(exc)
        out.append(["by_ip", max_age, res])
    return {"out": out, "state": {k: ser(v) for k, v in sorted(vars(view).items()) if k not in ("lock", "on_fresh_blocks", "_arp_plan", "_arp_small")}, "log": list(LOG)}


res_all = [sequence() for _ in range(N)]
digests = [hashlib.sha1(json.dumps(o).encode()).hexdigest() for o in res_all]
doc = {"digests": digests, "sample": res_all[:12]}
if os.environ.get("ARPVIEW_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(doc, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want["digests"]) == len(digests) == N
for i, (x, y) in enumerate(zip(digests, want["digests"])):
    assert x == y, "sequence %d differs: %s" % (i, json.dumps(res_all[i])[:900])
assert json.loads(json.dumps(res_all[:12])) == want["sample"]


def count(pred):
    return sum(1 for o in res_all if pred(o["log"]))


def has(log, kind, name=None, text=None):
    return any(l[0] == kind and (name is None or l[1] == name) and (text is None or text in l[2]) for l in log)


assert count(lambda lg: has(lg, "log", "info", "Rete grande")) > 100
assert count(lambda lg: has(lg, "log", "info", "Primo giro")) > 100
assert count(lambda lg: has(lg, "log", "info", "Rete di dimensione normale")) > 60
assert count(lambda lg: has(lg, "log", "warning")) > 80
assert count(lambda lg: has(lg, "log", "exception", "Scansione ARP fallita")) > 80
assert count(lambda lg: has(lg, "log", "debug")) > 60
assert count(lambda lg: has(lg, "fresh")) > 150
assert count(lambda lg: has(lg, "small")) > 150
assert count(lambda lg: has(lg, "mark")) > 150
assert count(lambda lg: not has(lg, "plan")) > 5, "sequences with only cache hits"
assert sum(1 for o in res_all for s in o["out"] if s[0] == "remember" and isinstance(s[1], dict) and "d" in s[1] and s[1]["d"]) > 100
assert sum(1 for o in res_all for s in o["out"] if s[0] == "remember" and isinstance(s[1], dict) and "exc" in s[1]) > 10
assert sum(1 for o in res_all if o["state"]["cache"] is not None and any(len(v) for v in [o["state"]["mem"]["d"]])) > 100
print("TUTTO OK")
