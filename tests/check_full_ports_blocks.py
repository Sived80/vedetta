"""The full port scan of a slow device, in the background, by blocks (scan/full_ports_plan.py and scan/rescan_background.py). Seen on the exports of 21-22 Oct: one `-p-` run of 900 s never finished on the slow devices
(10 timeouts in 14 hours, one after the other, each a quarter of an hour of probes for nothing) and was launched again at every deep search. Now: blocks of 4096 ports, each with its own limit; what a block finds is
saved at once and the next block is remembered on the card (the scan resumes there at the next deep search); a run stops after a few blocks; a block that times out is not repeated for a day, then two, four, seven
(capped); a card is due for the scan when it is in progress or never finished, unless it is waiting after a failure. The device is touched only with the same probes as before (the SYN scan of a range of ports)."""
import asyncio
import os
import sys
import tempfile
import types

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import full_ports_plan as plan, rescan, rescan_background as bg, scanner  # noqa: E402

DAY = 86400

# --- the blocks: contiguous, 4096 ports, the last one shorter, nothing after it
assert plan.block(1) == (1, 4096) and plan.block(4097) == (4097, 8192) and plan.block(61441) == (61441, 65535), plan.block(61441)
walked, start = [], 1
while start is not None:
    first, last = plan.block(start)
    walked.append((first, last))
    start = last + 1 if last < 65535 else None
assert len(walked) == 16 and walked[0][0] == 1 and walked[-1][1] == 65535 and all(b[0] == a[1] + 1 for a, b in zip(walked, walked[1:])), walked

# --- the pause after a failure: a day, two, four, seven and never more
assert [plan.retry_delay(n) for n in (1, 2, 3, 4, 5, 10)] == [DAY, 2 * DAY, 4 * DAY, 7 * DAY, 7 * DAY, 7 * DAY]
assert plan.retry_delay(0) == DAY, "a count that is missing or zero is the first failure"

# --- when a card is due: never finished, in progress, or older than a week with the services read; not while it waits after a failure
NOW, WEEK = 10_000_000.0, 7 * DAY
due = lambda info: plan.is_due(info, NOW, WEEK)  # noqa: E731
assert due({}) and due({"full_ports_at": NOW - 60}), "never finished the services / never scanned"
assert due({"full_ports_at": NOW - WEEK - 1, "services_at": NOW - 5}) and not due({"full_ports_at": NOW - WEEK + 60, "services_at": NOW - 5})
assert due({"full_ports_at": NOW - 60, "services_at": NOW - 5, "full_ports_next": 8193}), "in progress is due at once"
assert not due({"full_ports_next": 8193, "full_ports_retry_at": NOW + 3600}), "waiting after a failure"
assert due({"full_ports_next": 8193, "full_ports_retry_at": NOW - 1}), "the wait is over"
assert due({"full_ports_next": 8193, "full_ports_retry_at": NOW}), "the wait is over at the very second"
assert not due({"full_ports_at": NOW - 60, "services_at": NOW - 5, "full_ports_retry_at": NOW + 5}) and not due({"full_ports_retry_at": NOW + 5}), "the wait holds against every other reason"

# --- the run, with every collaborator replaced
CARD: dict = {}
CALLS: list = []
CLOCK = [NOW]
plan.PAUSE_S = 0
bg.time = types.SimpleNamespace(time=lambda: CLOCK[0], monotonic=lambda: 0.0)
bg.logger.info = lambda msg, *a, **k: CALLS.append(("info", msg % a if a else msg))
bg.logger.exception = lambda msg, *a, **k: CALLS.append(("exception", msg % a if a else msg))
bg._ports_found = lambda hosts: list(hosts)
bg.devices_config.load_devices = lambda: [dict(CARD)] if CARD else []
bg.devices_config.update_scan_info = lambda device_id, info: CARD.__setitem__("scan_info", dict(info)) or CALLS.append(("saved", dict(info)))
bg.touch_policy.may_touch = lambda device: True
bg.journal.add = lambda *a, **k: CALLS.append(("journal", a[1], k))


async def refresh(device_id, force=False):
    CALLS.append(("refresh", device_id))


bg.state.refresh_device = refresh
SERVICES: list = []


async def read_services(info, ip):
    SERVICES.append(ip)
    info["services_at"] = CLOCK[0]


bg._read_services = read_services
SCRIPT: list = []


async def fake_nmap(ip, args):
    CALLS.append(("nmap", ip, list(args)))
    step = SCRIPT.pop(0) if SCRIPT else []
    if step == "timeout":
        scanner.timed_out.add(ip)
        return []
    if step == "cancel":
        raise asyncio.CancelledError()
    return list(step)


bg._background_nmap = fake_nmap


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def fresh(scan_info=None):
    CARD.clear()
    CARD.update({"id": "d1", "ip": "10.0.0.5", "scan_info": dict(scan_info or {"slow_scan": True, "ports": [{"label": "80 · http"}]})})
    CALLS.clear(); SERVICES.clear(); SCRIPT.clear(); scanner.timed_out.clear()
    CLOCK[0] = NOW


nmaps = lambda: [c for c in CALLS if c[0] == "nmap"]  # noqa: E731
BLOCK_ARGS = lambda a, b: ["-T3", "-p", f"{a}-{b}", "--host-timeout", f"{plan.BLOCK_TIMEOUT_S}s", "10.0.0.5"]  # noqa: E731

# --- a run stops after its blocks and remembers where to go on; what each block finds is saved at once; the pause is between the blocks of a run, not after the last one
fresh()
SCRIPT += [[{"label": "5555"}], [], [{"label": "6053 · api"}]]
PAUSES: list = []
real_sleep = asyncio.sleep


async def recorded_sleep(seconds, *a, **k):
    PAUSES.append(seconds)
    await real_sleep(0)


plan.PAUSE_S = 7
asyncio.sleep = recorded_sleep
try:
    run(bg._scan_all_ports("d1", "10.0.0.5"))
finally:
    asyncio.sleep = real_sleep
    plan.PAUSE_S = 0
assert PAUSES == [7] * (plan.BLOCKS_PER_RUN - 1), PAUSES
assert len(nmaps()) == plan.BLOCKS_PER_RUN and nmaps()[0][2] == BLOCK_ARGS(1, 4096) and nmaps()[1][2] == BLOCK_ARGS(4097, 8192), nmaps()[:2]
assert CARD["scan_info"]["full_ports_next"] == 1 + plan.BLOCKS_PER_RUN * 4096 and "full_ports_at" not in CARD["scan_info"], CARD["scan_info"]
assert [p["label"] for p in CARD["scan_info"]["ports"]] == ["80 · http", "5555", "6053 · api"], "ports of the blocks joined to the card, by number"
assert not SERVICES and "-p-" not in repr(nmaps()), "no services before the end, and never the whole range in one run"

# --- the next run goes on from there until the end: then the scan is finished (time, services, refresh, one line for the log)
SCRIPT.clear(); CALLS.clear()
while "full_ports_next" in CARD["scan_info"]:
    before = CARD["scan_info"]["full_ports_next"]
    run(bg._scan_all_ports("d1", "10.0.0.5"))
    assert nmaps()[0][2] == BLOCK_ARGS(before, min(before + 4095, 65535)), (before, nmaps()[0])
    CALLS.clear()
    assert CARD["scan_info"].get("full_ports_next", 99999) > before
info = CARD["scan_info"]
assert info["full_ports_at"] == NOW and info["services_at"] == NOW and SERVICES == ["10.0.0.5"], info
assert not any(k in info for k in ("full_ports_next", "full_ports_failures", "full_ports_retry_at", "full_ports_base")), info

# --- a block that times out: the earlier ones stay saved, the same block is next, a day of pause, a journal entry, no services
fresh()
SCRIPT += [[{"label": "5555"}], "timeout"]
run(bg._scan_all_ports("d1", "10.0.0.5"))
info = CARD["scan_info"]
assert len(nmaps()) == 2 and info["full_ports_next"] == 4097 and info["full_ports_failures"] == 1 and info["full_ports_retry_at"] == NOW + DAY, info
assert [p["label"] for p in info["ports"]] == ["80 · http", "5555"] and not SERVICES and "10.0.0.5" not in scanner.timed_out
assert any(c[0] == "journal" and c[1] == "journal.fullports_failed" for c in CALLS), CALLS
# the second failure of the same block: two days; a success clears the failures
fresh(dict(info))
SCRIPT += ["timeout"]
run(bg._scan_all_ports("d1", "10.0.0.5"))
assert CARD["scan_info"]["full_ports_failures"] == 2 and CARD["scan_info"]["full_ports_retry_at"] == NOW + 2 * DAY
fresh(dict(CARD["scan_info"]))
run(bg._scan_all_ports("d1", "10.0.0.5"))
assert "full_ports_failures" not in CARD["scan_info"] and "full_ports_retry_at" not in CARD["scan_info"], CARD["scan_info"]

# --- the card is gone or became «don't touch» between blocks: it stops, nothing is sent after that, nothing saved
fresh()
bg.touch_policy.may_touch = lambda device: False
run(bg._scan_all_ports("d1", "10.0.0.5"))
assert not nmaps() and not any(c[0] == "saved" for c in CALLS)
bg.touch_policy.may_touch = lambda device: True
fresh(); CARD.clear()
run(bg._scan_all_ports("d1", "10.0.0.5"))
assert not nmaps() and not any(c[0] == "saved" for c in CALLS)

# --- a cancellation goes through (the service stops); an error of the scan is logged and does not stop the service
fresh(); SCRIPT += ["cancel"]
try:
    run(bg._full_ports_background("d1", "10.0.0.5"))
    raise AssertionError("cancelled must go through")
except asyncio.CancelledError:
    pass
fresh()


async def boom(ip, args):
    raise OSError("no nmap")


bg._background_nmap = boom
run(bg._full_ports_background("d1", "10.0.0.5"))
assert any(c[0] == "exception" and "fallita" in c[1] for c in CALLS), CALLS
bg._background_nmap = fake_nmap

# --- a deep search keeps the state of the scan on a slow device (it replaces the rest of the card)
slow = {"slow_scan": True}
fields = {}
rescan._keep_ports_of_slow_device(fields, slow, {"scan_info": {"ports": [], "full_ports_next": 8193, "full_ports_base": 3, "full_ports_failures": 2, "full_ports_retry_at": NOW + 5, "full_ports_at": 7}})
assert {k: fields.get(k) for k in ("full_ports_next", "full_ports_base", "full_ports_failures", "full_ports_retry_at", "full_ports_at")} == {"full_ports_next": 8193, "full_ports_base": 3, "full_ports_failures": 2, "full_ports_retry_at": NOW + 5, "full_ports_at": 7}, fields
print("check_full_ports_blocks OK")
