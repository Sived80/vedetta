"""Golden-master test of scan/rescan_background._full_ports_background (the slow device's full port scan in the background): 3000 generated runs - the first scan answering, empty, failing, timing out or cancelled;
the device gone from the configuration; ports found and already known, ephemeral or not; the second scan (services) answering, empty, timing out or failing; the saving or the refresh failing - with every
collaborator replaced by a recorder (and the clock by a counter) must give exactly the same outcome and make exactly the same calls and log lines (arguments included, in order) as the code before the function
was split into smaller ones; digests and a readable sample are stored in tests/golden/full_ports.json.
Regenerate only on purpose:  FULL_PORTS_GOLDEN_UPDATE=1 python tests/check_full_ports_golden.py"""
import asyncio
import hashlib
import json
import os
import random
import sys
import types
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.applog import logger  # noqa: E402
from app.scan import rescan, rescan_background, scanner  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "full_ports.json"
N = 3000
rng = random.Random(9090)
LOG: list = []
M: dict = {}
CLOCK = [1000.0]


def pick(seq):
    return seq[rng.randrange(len(seq))]


def jcopy(x):
    return json.loads(json.dumps(x, default=str, sort_keys=True))


logger.info = lambda msg, *a, **k: LOG.append(["info", str(msg), [str(x) for x in a]])
logger.exception = lambda msg, *a, **k: LOG.append(["exception", str(msg), [str(x) for x in a]])


def fake_time():
    CLOCK[0] += 1
    return CLOCK[0]


rescan_background.time = types.SimpleNamespace(time=fake_time, monotonic=lambda: 0.0)


async def fake_run_nmap(args, semaphore=None):
    LOG.append(["_run_nmap", list(args), semaphore is rescan_background._BG_NMAP_SEM])
    step = M["steps"].pop(0)
    if step == "cancel":
        raise asyncio.CancelledError()
    if isinstance(step, Exception):
        raise step
    return step


def fake_parse_hosts(xml):
    LOG.append(["_parse_hosts", xml])
    return M["hosts"][xml]


def fake_format(info):
    LOG.append(["format_scan_info", jcopy(info)])
    return {"ports": info["ports"]} if info["ports"] else {}


def fake_load():
    LOG.append(["load_devices"])
    return [dict(d) for d in M["devices"]]


def fake_update(device_id, info):
    LOG.append(["update_scan_info", device_id, jcopy(info)])
    if M["update"]:
        raise OSError("disk")


async def fake_refresh(device_id, force=False):
    LOG.append(["refresh_device", device_id, force])
    if M["refresh"]:
        raise RuntimeError("refresh")


scanner._run_nmap, scanner._parse_hosts, scanner.format_scan_info = fake_run_nmap, fake_parse_hosts, fake_format
rescan_background.devices_config.load_devices, rescan_background.devices_config.update_scan_info = fake_load, fake_update
rescan_background.state.refresh_device = fake_refresh
rescan_background.journal.add = lambda *a, **k: LOG.append(["journal.add", jcopy(list(a)), jcopy(k)])

LABELS = ["80 · http", "22", "443 · https", "8080", "50000", "60000 · x", "bad", "", "9100 · raw"]


def ports(k=None):
    if rng.random() < 0.08:        # many open ports, in an order that is not the numeric one
        return [{"label": "%d · s" % rng.randrange(1, 49000)} for _ in range(rng.randrange(35, 60))]
    return [{"label": pick(LABELS), **pick([{}, {"v": 1}])} for _ in range(rng.randrange(0, 5) if k is None else k)]


def failure():
    return pick([RuntimeError("nmap down"), OSError("no nmap"), ValueError("v")])


async def run_one(ip):
    M.clear()
    first = pick(["x1"] * 6 + [failure(), "cancel"])
    second = pick(["x2"] * 6 + [failure(), "cancel"])
    steps = [first, second]
    hosts = {"x1": pick([[{"ports": ports()}], [{"ports": ports()}], [{"ports": ports()}, {"ports": ports()}], []]), "x2": pick([[{"ports": ports()}], [{"ports": ports()}], [{"ports": ports()}, {"ports": ports()}], []])}
    dev = pick([None, {"id": "dev1", "ip": ip}, {"id": "dev1", "scan_info": None}, {"id": "dev1", "scan_info": {"ports": ports(), "http_title": "t", "services_at": 5, "full_ports_at": 4}}, {"id": "dev1", "scan_info": {"ports": ports(), "slow_scan": True}},
                {"id": "other"}])
    M.update(steps=steps, hosts=hosts, devices=[d for d in [dev, {"id": "dev2"}] if d is not None], update=rng.random() < 0.08, refresh=rng.random() < 0.08)
    scanner.timed_out.clear()
    plan = pick([[], [], [], ["after_first"], ["after_second"], ["after_first", "after_second"]])
    # timed out markers are added by the first/second scan through a wrapper on the parse step
    orig = fake_parse_hosts

    def parse(xml):
        if ("after_first" in plan and xml == "x1") or ("after_second" in plan and xml == "x2"):
            scanner.timed_out.add(ip)
        return orig(xml)
    scanner._parse_hosts = parse
    try:
        await rescan_background._full_ports_background("dev1", ip)
        outcome = "done"
    except asyncio.CancelledError:
        outcome = "cancelled"
    return [outcome, plan, [str(s) for s in steps], sorted(scanner.timed_out)], dev


loop = asyncio.new_event_loop()
out = []
for _ in range(N):
    LOG.clear()
    res, dev = loop.run_until_complete(run_one(pick(["10.0.0.5", "10.0.0.6"])))
    out.append({"res": jcopy(res), "dev": jcopy(dev), "log": jcopy(LOG)})


def digest(x):
    return hashlib.sha1(json.dumps(x, default=str, sort_keys=True).encode()).hexdigest()[:20]


result = {"digests": [digest(o) for o in out], "sample": out[:6]}
if os.environ.get("FULL_PORTS_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(result, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want["digests"]) == len(result["digests"]) == N
for i, (x, y) in enumerate(zip(result["digests"], want["digests"])):
    assert x == y, "run %d differs: %s" % (i, json.dumps(out[i], default=str)[:900])
assert result["sample"] == want["sample"]
c = lambda f: sum(1 for o in out if f(o))  # noqa: E731
has = lambda o, name: any(e[0] == name for e in o["log"])  # noqa: E731
stats = {"cancelled": c(lambda o: o["res"][0] == "cancelled"), "timeout1": c(lambda o: any("scaduta" in str(e) for e in o["log"])), "gone": c(lambda o: has(o, "load_devices") and not has(o, "update_scan_info") and not has(o, "exception")),
         "saved": c(lambda o: has(o, "update_scan_info")), "services": c(lambda o: sum(1 for e in o["log"] if e[0] == "_run_nmap") == 2), "svc_fail": c(lambda o: any("riconoscimento" in str(e) for e in o["log"])),
         "svc_merge": c(lambda o: has(o, "update_scan_info") and sum(1 for e in o["log"] if e[0] == "format_scan_info") == 2), "failed": c(lambda o: any("fallita" in str(e) and e[0] == "exception" for e in o["log"])),
         "journal": c(lambda o: has(o, "journal.add")), "refresh_fail": c(lambda o: has(o, "refresh_device") and any(e[0] == "exception" for e in o["log"])), "added_neg": c(lambda o: any(e[0] == "info" and e[2] and e[2][-1].startswith("-") for e in o["log"])),
         "no_open": c(lambda o: has(o, "update_scan_info") and sum(1 for e in o["log"] if e[0] == "_run_nmap") == 1), "svc_timeout": c(lambda o: has(o, "update_scan_info") and any(e[0] == "_parse_hosts" and e[1] == "x2" for e in o["log"]) and o["res"][1] and "after_second" in o["res"][1])}
for key, low in (("cancelled", 100), ("timeout1", 100), ("gone", 100), ("saved", 800), ("services", 600), ("svc_fail", 60), ("svc_merge", 120), ("failed", 100), ("journal", 600), ("refresh_fail", 30), ("added_neg", 5), ("no_open", 20), ("svc_timeout", 30)):
    assert stats[key] >= low, ("scenarios too uniform", key, stats)
print("TUTTO OK")
