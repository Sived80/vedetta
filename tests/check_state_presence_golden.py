"""Golden-master test of the presence of DeviceState (who is online: the consecutive misses, when each device was last seen, what the history last recorded): 2500 generated sequences
of operations - _record_presence with online/offline transitions (a repeated state is not written again; ip or mac missing or empty), load_history reading the saved state (also failing,
and with a MAC lookup that gives nothing, an empty text or a MAC), remove of a device that is there or not, the history failing to write - with the history and the log replaced
must give exactly the dictionaries _misses, _last_seen, _db_state and _last_mac after every step, the calls to the history (with their arguments and in order), the log lines of the
failures and how many background tasks are alive, stored in tests/golden/state_presence.json, written from the code as it was before the presence moved out of DeviceState (a digest per
sequence plus a readable sample).
Regenerate only on purpose:  STATE_PRESENCE_GOLDEN_UPDATE=1 python tests/check_state_presence_golden.py"""
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
from app import state as state_mod  # noqa: E402
from app.applog import logger  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "state_presence.json"
N = 2500
rng = random.Random(7531)
LOG: list = []
logger.exception = lambda msg, *a, **k: LOG.append(["logger.exception", str(msg), [str(x) for x in a]])
IDS = ["d1", "d2", "d3"]


def pick(seq):
    return seq[rng.randrange(len(seq))]


async def main():
    out = []
    for _ in range(N):
        LOG.clear()
        st = state_mod.DeviceState()
        st.emit_event = lambda event: None
        for i in rng.sample(IDS, rng.randrange(0, 3)):
            st._misses[i] = pick([0, 1, 2])
        mode = {"load": pick(["ok", "ok", "ok", "raise"]), "write": pick(["ok", "ok", "ok", "raise_os", "raise_rt"]), "mac": pick(["mac", "mac", "empty", "none"])}
        data = {i: (rng.random() < 0.5, pick([100.0, 250.5])) for i in rng.sample(IDS, rng.randrange(0, 4))}

        def last_presence():
            LOG.append(["last_presence"])
            if mode["load"] == "raise":
                raise RuntimeError("history down")
            return dict(data)

        def last_mac(device_id):
            LOG.append(["last_mac", device_id])
            return {"mac": "aa:bb:" + device_id, "empty": "", "none": None}[mode["mac"]]

        def record_presence(*args):
            LOG.append(["record_presence", list(args)])
            if mode["write"] == "raise_os":
                raise OSError("disk full")
            if mode["write"] == "raise_rt":
                raise RuntimeError("history broken")

        state_mod.history = types.SimpleNamespace(last_presence=last_presence, last_mac=last_mac, record_presence=record_presence)
        steps = []
        for _ in range(rng.randrange(1, 12)):
            op = pick(["rec", "rec", "rec", "rec", "load", "remove", "remove", "peek"])
            arg = None
            try:
                if op == "rec":
                    device_id = pick(IDS)
                    arg = [{"id": device_id, **pick([{"ip": "10.0.0.5", "mac": "aa:bb"}, {"ip": None, "mac": None}, {}, {"ip": "10.0.0.6", "mac": ""}])}, rng.random() < 0.5, pick([5.0, 99.5])]
                    st._record_presence(*arg)
                elif op == "load":
                    data.clear()
                    data.update({i: (rng.random() < 0.5, pick([100.0, 250.5])) for i in rng.sample(IDS, rng.randrange(0, 4))})
                    mode["mac"] = pick(["mac", "empty", "none"])
                    await st.load_history()
                elif op == "remove":
                    arg = pick(IDS)
                    if rng.random() < 0.8:
                        st.devices[arg] = {"id": arg}
                    st.remove(arg)
                err = None
            except Exception as exc:
                err = type(exc).__name__
            tasks = list(st._bg)
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            steps.append([op, arg, err, dict(st._misses), dict(st._last_seen), dict(st._db_state), dict(st._last_mac), len(LOG), len(st._bg)])
        out.append({"steps": steps, "log": list(LOG)})
    return out


out = asyncio.run(main())


def digest(x):
    return hashlib.sha1(json.dumps(x, default=str).encode()).hexdigest()[:20]


result = {"digests": [digest(o) for o in out], "sample": json.loads(json.dumps(out[:8], default=str))}
if os.environ.get("STATE_PRESENCE_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(result, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want["digests"]) == len(result["digests"]) == N
for i, (x, y) in enumerate(zip(result["digests"], want["digests"])):
    assert x == y, "sequence %d differs: %s" % (i, json.dumps(out[i], default=str)[:700])
assert result["sample"] == want["sample"]
logs = [e for o in out for e in o["log"]]
steps = [s for o in out for s in o["steps"]]
c = lambda f, seq: sum(1 for x in seq if f(x))  # noqa: E731
stats = {"writes": c(lambda e: e[0] == "record_presence", logs), "write_fail": c(lambda e: e[0] == "logger.exception" and "Salvataggio" in e[1], logs),
         "load_fail": c(lambda e: e[0] == "logger.exception" and "Lettura" in e[1], logs), "last_mac": c(lambda e: e[0] == "last_mac", logs),
         "removed_known": c(lambda s: s[0] == "remove" and s[1] is not None and s[5].get(s[1]) is None and s[3].get(s[1]) is None, steps),
         "seen": c(lambda s: s[4], steps), "db": c(lambda s: s[5], steps), "mac_set": c(lambda s: s[6], steps)}
for key, low in (("writes", 1500), ("write_fail", 150), ("load_fail", 50), ("last_mac", 200), ("removed_known", 100), ("seen", 300), ("db", 800), ("mac_set", 150)):
    assert stats[key] >= low, ("scenarios too uniform", key, stats)
print("TUTTO OK")
