"""Golden-master test of DeviceState.diagnostics (how the service is doing, for the export: sizes, times and counts): 2500 generated situations - network known, not known or not
valid (host bits, IPv6, text), searched in blocks or as a whole (with the plan missing a key), paused or not (0.0 and infinity included), the MAC layer summary working, failing or empty,
the process status file missing, normal, partial or broken - with the clock frozen and the collaborators in memory must give exactly the dictionary (with the ORDER of its keys, or the
exception) and the calls made (the log of the failure, the file opened, the report asked) stored in tests/golden/state_diagnostics.json, written from the code as it was before the
method was moved to state_support.py (a digest per case plus a readable sample).
Regenerate only on purpose:  STATE_DIAG_GOLDEN_UPDATE=1 python tests/check_state_diagnostics_golden.py"""
import builtins
import hashlib
import io
import json
import os
import random
import sys
import tempfile
import time
import types
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()      # never the real folder of the developer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import maclayer, state as state_mod  # noqa: E402
from app.applog import logger  # noqa: E402
from app.scan import dhcp  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "state_diagnostics.json"
N = 2500
rng = random.Random(8642)
FROZEN = 1_700_000_000.0
LOG: list = []
real_open = builtins.open
time.time = lambda: FROZEN
logger.exception = lambda msg, *a, **k: LOG.append(["logger.exception", str(msg)])


def pick(seq):
    return seq[rng.randrange(len(seq))]


NETS = [None, (), ("eth0", "192.168.1.0/24"), ("eth0", "192.168.1.5/24"), ("eth0", "10.0.0.0/8"), ("eth0", "172.16.4.0/22"), ("eth0", "2001:db8::/64"), ("eth0", "not a network"),
        ("eth0", "192.168.1.0/33")]
PLANS = [None, None, {"total": 4, "done": 1}, {"total": 256, "done": 256}, {"total": 0, "done": 0}, {"total": 9}]
PROC = {
    "normal": "Name:\tx\nVmRSS:\t 123456 kB\nThreads:\t 7\n",
    "threads_only": "Threads: 12\n",
    "rss_only": "VmRSS:\t2048 kB\n",
    "broken_rss": "VmRSS: abc kB\nThreads: 3\n",
    "broken_after": "Threads: 5\nVmRSS: zz kB\n",
    "empty": "",
    "other": "Name:\tx\nState:\tS\n",
}


def case():
    LOG.clear()
    st = state_mod.DeviceState()
    st._view = types.SimpleNamespace(net=pick(NETS), plan_info=pick(PLANS), asked=pick([0, 5, 254]), found=pick([0, 3, 40]))
    st._stats = types.SimpleNamespace(total_cycles=pick([0, 7, 120]), slowest=pick([0.0, 1.2345, 33.3333, 0.05]), total_chains=pick([0, 2, 9]),
                                      last_summary=pick([None, {"cycles": 3}, "x"]))
    left = pick([None, None, 0.0, 12.5, float("inf")])
    st._pause = types.SimpleNamespace(remaining=lambda: left, total=0)
    st.devices = {str(i): {} for i in range(rng.randrange(0, 6))}
    interval_mode = pick(["ok", "ok", "ok", "raise"])

    def poll_interval():
        if interval_mode == "raise":
            raise RuntimeError("settings down")
        return pick([10, 30, 300])

    state_mod.settings = types.SimpleNamespace(poll_interval=poll_interval, DEFAULTS={"poll_interval": 30})
    state_mod._PROCESS_START = FROZEN - pick([0.0, 5.9, 4000.7])
    sum_mode = pick(["ok", "ok", "ok", "empty", "raise"])
    rep_mode = pick(["ok", "ok", "empty", "raise"])

    def maclayer_summary():
        LOG.append(["maclayer_summary"])
        if sum_mode == "raise":
            raise RuntimeError("no summary")
        return {} if sum_mode == "empty" else {"known": 4, "n": 1}

    def observation_report(history, seen):
        LOG.append(["observation_report", history is fake_history, sorted(seen)])
        if rep_mode == "raise":
            raise ValueError("no report")
        return {} if rep_mode == "empty" else {"n": 2, "observed": 9}

    fake_history = types.SimpleNamespace(maclayer_summary=maclayer_summary)
    state_mod.history = fake_history
    maclayer.observation_report = observation_report
    dhcp.seen = {pick(["aa:bb", "cc:dd"]): {}} if rng.random() < 0.6 else {}
    proc = pick(list(PROC) + ["missing", "missing"])

    def fake_open(path, *a, **k):
        if path == "/proc/self/status":
            LOG.append(["open", path, k.get("encoding")])
            if proc == "missing":
                raise FileNotFoundError(2, "no such file")
            return io.StringIO(PROC[proc])
        return real_open(path, *a, **k)

    builtins.open = fake_open
    try:
        entry = {"res": st.diagnostics()}
    except Exception as exc:
        entry = {"exc": type(exc).__name__}
    finally:
        builtins.open = real_open
    entry["log"] = list(LOG)
    return entry


out = [case() for _ in range(N)]


def digest(x):
    return hashlib.sha1(json.dumps(x, default=str).encode()).hexdigest()[:20]      # key order matters: no sort_keys


result = {"digests": [digest(o) for o in out], "sample": json.loads(json.dumps(out[:14], default=str))}
if os.environ.get("STATE_DIAG_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(result, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want["digests"]) == len(result["digests"]) == N
for i, (x, y) in enumerate(zip(result["digests"], want["digests"])):
    assert x == y, "case %d differs: %s" % (i, json.dumps(out[i], default=str)[:600])
assert result["sample"] == want["sample"]
res = [o["res"] for o in out if "res" in o]
c = lambda f: sum(1 for r in res if f(r))  # noqa: E731
stats = {"network": c(lambda r: "network" in r), "blocks": c(lambda r: "blocks_total" in r.get("network", {})), "whole": c(lambda r: r.get("network", {}).get("mode") == "whole"),
         "mac": c(lambda r: "mac_layer" in r), "mac_empty": c(lambda r: r.get("mac_layer") == {}), "no_mac": c(lambda r: "mac_layer" not in r), "rss": c(lambda r: "rss_mb" in r),
         "threads_no_rss": c(lambda r: "threads" in r and "rss_mb" not in r), "paused": c(lambda r: r["paused"]), "exc": sum(1 for o in out if "exc" in o),
         "logged": sum(1 for o in out if any(e[0] == "logger.exception" for e in o["log"]))}
for key, low in (("network", 800), ("blocks", 150), ("whole", 150), ("mac", 800), ("mac_empty", 40), ("no_mac", 150), ("rss", 400), ("threads_no_rss", 100), ("paused", 400), ("exc", 20), ("logged", 150)):
    assert stats[key] >= low, ("scenarios too uniform", key, stats)
print("TUTTO OK")
