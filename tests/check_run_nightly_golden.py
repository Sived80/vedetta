"""Golden-master test of maintenance.run_nightly (the night job: deep search again on the devices whose data is older than STALE_DAYS, pruning of the history, update of the MAC prefix
database): 3000 generated runs with the collaborators replaced by deterministic in-memory ones - a frozen clock, a fake list of configured devices (fresh, stale, never searched, with
scanned_at or deep_empty_at, with falsy values), a fake local-address filter, a fake batch preparation, a fake per-device search that fails for some, a fake history prune, fake
prefix-database functions (enabled or not, due or not, failing in each of the three calls), a fake logger - must give exactly the return value (or the exception) AND the ORDER of every
call with its arguments (clock reads, loading, filtering, log lines with their arguments, batch, per-device search, prune, prefix database) stored in tests/golden/run_nightly.json,
written from the code as it was before the function was split (digest per case plus a readable sample).
Regenerate only on purpose:  RUN_NIGHTLY_GOLDEN_UPDATE=1 python tests/check_run_nightly_golden.py"""
import asyncio
import hashlib
import json
import os
import random
import sys
import tempfile
import types
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()      # never the real folder of the developer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import maintenance  # noqa: E402
from app.recognition import oui_update  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "run_nightly.json"
N = 3000
rng = random.Random(3003)
NOW = 10_000_000.0
CUT = NOW - 7 * 86400
LOG: list = []
SET: dict = {}


def pick(seq):
    return seq[rng.randrange(len(seq))]


class FakeTime:
    @staticmethod
    def time():
        LOG.append(["time"])
        return NOW


class FakeLogger:
    @staticmethod
    def info(fmt, *args):
        LOG.append(["info", fmt, [str(a) for a in args]])

    @staticmethod
    def warning(fmt, *args):
        LOG.append(["warning", fmt, [str(a) for a in args]])

    @staticmethod
    def exception(fmt, *args):
        LOG.append(["exception", fmt, [str(a) for a in args]])


def fake_load_devices():
    LOG.append(["load_devices"])
    if SET["load_fails"]:
        raise OSError("no file")
    return SET["devices"]


async def fake_filter_local_ips(ips):
    LOG.append(["filter", list(ips)])
    if SET["filter_fails"]:
        raise RuntimeError("filter")
    return [ip for ip in ips if ip not in SET["remote"]] + (["10.99.99.99"] if SET["extra_local"] else [])


async def fake_prepare_batch(profile, ips):
    LOG.append(["prepare_batch", profile, list(ips)])
    if SET["batch_fails"]:
        raise RuntimeError("batch")
    return {"batch": len(ips)}


async def fake_rescan_device(device, batch):
    LOG.append(["rescan", device["ip"], batch])
    if device["ip"] in SET["rescan_fails"]:
        raise ValueError("rescan " + device["ip"])


def fake_prune():
    LOG.append(["prune"])
    if SET["prune_fails"]:
        raise OSError("db")
    return SET["pruned"]


def fake_auto_update_enabled():
    LOG.append(["auto_update_enabled"])
    if SET["oui_fails"] == 1:
        raise OSError("enabled")
    return SET["oui_enabled"]


def fake_is_due():
    LOG.append(["is_due"])
    if SET["oui_fails"] == 2:
        raise ValueError("due")
    return SET["oui_due"]


def fake_update():
    LOG.append(["oui_update"])
    if SET["oui_fails"] == 3:
        raise RuntimeError("download")
    return {}


maintenance.time = FakeTime
maintenance.logger = FakeLogger
maintenance.devices_config = types.SimpleNamespace(load_devices=fake_load_devices)
maintenance.filter_local_ips = fake_filter_local_ips
maintenance.pipeline = types.SimpleNamespace(prepare_batch=fake_prepare_batch)
maintenance.rescan_device = fake_rescan_device
maintenance.history = types.SimpleNamespace(prune=fake_prune)
oui_update.auto_update_enabled = fake_auto_update_enabled
oui_update.is_due = fake_is_due
oui_update.update = fake_update

IPS = ["192.168.1.%d" % i for i in range(2, 9)]


def device():
    d = {"ip": pick(IPS)}
    r = rng.random()
    if r < 0.15:
        pass                                                            # never searched: no scan_info
    elif r < 0.25:
        d["scan_info"] = pick([None, {}, "text", 0])
    else:
        info = {}
        if rng.random() < 0.8:
            info["scanned_at"] = pick([CUT - 1, CUT, CUT + 1, NOW - 100, 0, None, 5.5, CUT - 86400 * 30])
        if rng.random() < 0.5:
            info["deep_empty_at"] = pick([CUT - 1, CUT, CUT + 1, NOW - 100, 0, None, CUT - 5000])
        d["scan_info"] = info
    if rng.random() < 0.01:
        del d["ip"]
    return d


def run_case():
    LOG.clear()
    SET.update(load_fails=rng.random() < 0.03, filter_fails=rng.random() < 0.04, batch_fails=rng.random() < 0.05, prune_fails=rng.random() < 0.04,
               remote=set(rng.sample(IPS, rng.randrange(0, 4))), extra_local=rng.random() < 0.1, pruned=pick([0, 3, 120]),
               rescan_fails=set(rng.sample(IPS, rng.randrange(0, 3))), oui_enabled=rng.random() < 0.6, oui_due=rng.random() < 0.6,
               oui_fails=pick([0, 0, 0, 0, 0, 0, 1, 2, 3]))
    SET["devices"] = [device() for _ in range(rng.randrange(0, 7))]
    try:
        r = loop.run_until_complete(maintenance.run_nightly())
        res = {"ret": r}
    except BaseException as exc:
        res = {"exception": type(exc).__name__}
    res["log"] = json.loads(json.dumps(LOG))
    return res


loop = asyncio.new_event_loop()
cases = [run_case() for _ in range(N)]
loop.close()
digests = [hashlib.sha1(json.dumps(c).encode()).hexdigest()[:12] for c in cases]
out = json.loads(json.dumps({"digests": digests, "sample": cases[:12]}))
if os.environ.get("RUN_NIGHTLY_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(out, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want["digests"]) == len(digests) == N
for i, (x, y) in enumerate(zip(digests, want["digests"])):
    assert x == y, "case %d differs: %s" % (i, json.dumps(cases[i])[:900])
assert out["sample"] == want["sample"]
ex = [c for c in cases if "exception" in c]
assert 20 < len(ex) < 900, len(ex)
evs = [[e[0] for e in c["log"]] for c in cases]
kinds = [{e[0] for e in c["log"]} for c in cases]
assert sum(1 for k in kinds if "rescan" in k) > 1000 and sum(1 for k in kinds if "prepare_batch" in k) > 1200 and sum(1 for k in kinds if "oui_update" in k) > 600
assert sum(1 for c in cases if any(e[0] == "exception" and e[1].startswith("Manutenzione notturna: scansione") for e in c["log"])) > 300
assert sum(1 for c in cases if any(e[0] == "warning" for e in c["log"])) > 200
assert sum(1 for k in kinds if "filter" not in k and "load_devices" in k and "prune" in k) > 100, "no case without stale devices"
assert sum(1 for c in cases if any(e[0] == "info" and e[2] == ["0"] and e[1].startswith("Manutenzione notturna:") for e in c["log"])) > 100
assert sum(1 for k in kinds if "filter" in k and "prepare_batch" not in k) > 50, "no case where every stale device is remote"
assert sum(1 for L in evs if "auto_update_enabled" in L and "is_due" not in L) > 100 and sum(1 for L in evs if "is_due" in L and "oui_update" not in L) > 100
assert sum(1 for L in evs if L.count("rescan") >= 3) > 100
print("TUTTO OK")
