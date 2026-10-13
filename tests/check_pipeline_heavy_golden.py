"""Golden-master test of three functions of the scan pipeline (prepare_batch, _run_parallel_probes, _probe_shelly_adapter): 3000 generated calls with every scanner, discovery and adapter call replaced by a
recorder (that answers, answers nothing or fails) must give exactly the same answer, leave the same state behind (the batch, the info, the set of timed-out hosts) and make exactly the same calls and
log lines (arguments included, in order) as the code before they were split into smaller ones; digests and a readable sample are stored in tests/golden/pipeline_heavy.json.
Regenerate only on purpose:  PIPELINE_HEAVY_GOLDEN_UPDATE=1 python tests/check_pipeline_heavy_golden.py"""
import asyncio
import copy
import dataclasses
import hashlib
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.applog import logger  # noqa: E402
from app.scan import discovery, pipeline_plan, pipeline_probes, scanner  # noqa: E402
from app.scan.adapters import shelly_gen1, shelly_gen2  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "pipeline_heavy.json"
N = 3000
rng = random.Random(31337)
LOG: list = []
M: dict = {}


def pick(seq):
    return seq[rng.randrange(len(seq))]


def jcopy(x):
    return json.loads(json.dumps(x, default=str, sort_keys=True))


logger.info = lambda msg, *a, **k: LOG.append(["info", str(msg), [str(x) for x in a]])
logger.error = lambda msg, *a, **k: LOG.append(["error", str(msg), [str(x) for x in a]])


def recorder(name, key):
    async def f(*args, **kwargs):
        LOG.append([name, jcopy(list(args)), jcopy(kwargs)])
        v = M[key]
        if isinstance(v, Exception):
            raise v
        return v
    return f


def sync_recorder(name, key):
    def f(*args, **kwargs):
        LOG.append([name, jcopy(list(args)), jcopy(kwargs)])
        return M[key]
    return f


scanner.resolve_names, scanner.mdns_scan, scanner.ssdp_scan, scanner.igmp_scan = (recorder("resolve_names", "names"), recorder("mdns_scan", "names"), recorder("ssdp_scan", "ssdp"), recorder("igmp_scan", "igmp"))
discovery.wsd_scan = recorder("wsd_scan", "wsd")
pipeline_plan.get_local_network = recorder("get_local_network", "net")
pipeline_plan.settings.flows_load = lambda: {"deep": M["flow"], "quick": ["ports_fast"]}
scanner._run_nmap = recorder("_run_nmap", "xml")
scanner.protocol_scan = recorder("protocol_scan", "proto")
discovery.rtsp_probe = recorder("rtsp_probe", "rtsp")
scanner._parse_hosts = sync_recorder("_parse_hosts", "hosts")
scanner.fast_ports = recorder("fast_ports", "fast")
shelly_gen1.probe = recorder("shelly_gen1.probe", "gen1")
shelly_gen2.battery_probe = recorder("shelly_gen2.battery_probe", "gen2")

STEPS = ["mdns", "reverse_names", "ssdp", "onvif", "igmp", "ports_fast", "adapter_probe", "tls_ssh", "rtsp", "netbios_snmp"]


def maybe_fail(value):
    return pick([value, value, value, RuntimeError("boom"), ValueError("bad")])


async def case_batch():
    steps = pick([None] + [rng.sample(STEPS, rng.randrange(0, 7)) for _ in range(6)])
    M.clear()
    M.update(flow=rng.sample(STEPS, rng.randrange(0, 6)), names=maybe_fail({"10.0.0.1": "cam", "10.0.0.2": "tv"}), ssdp=maybe_fail({"10.0.0.1": {"name": "n"}}), igmp=maybe_fail({"10.0.0.2": ["a", "b"]}),
             wsd=maybe_fail({"10.0.0.3": {"name": "w"}}), net=pick([("192.168.1.0/24", "192.168.1.9"), RuntimeError("no net")]))
    ips = rng.sample(["10.0.0.1", "10.0.0.2", "10.0.0.3", "10.0.0.4"], rng.randrange(0, 5))
    batch = await pipeline_plan.prepare_batch(pick(["deep", "quick"]), ips, steps)
    return ["batch", [steps, ips, M["flow"]], dataclasses.asdict(batch)]


async def case_parallel():
    M.clear()
    ip = pick(["10.0.0.1", "10.0.0.2"])
    host = {"ip": ip, "mac": pick([None, "aa:bb:cc:dd:ee:01"]), "hostname": pick([None, "h"]), "ports": pick([[], [{"port": 80}], [{"port": 22}, {"port": 443}]]), "http_title": pick([None, "T"])}
    M.update(xml=pick(["<xml/>", ""]), proto=maybe_fail({"netbios_name": "n", "snmp_descr": "s"}) if False else pick([{"netbios_name": "n"}, {}]), rtsp=pick([{"rtsp_server": "r"}, {}]),
             hosts=pick([[host], [], [host, dict(host, ip="10.0.0.9")]]), fast=pick([{"ports": [{"port": 8080}], "http_title": "F"}, {"ports": []}, None, RuntimeError("fast down")]))
    nmap_args = pick([None, [], ["-p-"], ["-T4", "-p-", ip]])
    chosen = set(rng.sample(["netbios_snmp", "rtsp", "ssdp", "http_title"], rng.randrange(0, 5)))
    slow = pick([True, False])
    scanner.timed_out.clear()
    if rng.random() < 0.4:
        scanner.timed_out.add(ip)
    protocol_info, rtsp_info, info = await pipeline_probes._run_parallel_probes(nmap_args, ip, slow, chosen)
    return ["parallel", [nmap_args, ip, slow, sorted(chosen)], [protocol_info, rtsp_info, info, sorted(scanner.timed_out)]]


async def case_shelly():
    M.clear()
    ports = pick([[], [{"port": 80}], [{"port": 80}], [{"port": 22}], [{"port": 80}, {"port": 443}]])
    info = {"ports": ports, **pick([{}, {"battery": "old"}])}
    M.update(gen1=pick([{"mac": "aa:bb", "uptime_seconds": 5, "battery": pick([None, True])}, {"mac": "aa:bb", "uptime_seconds": 0}, {"mac": "aa:bb", "uptime_seconds": None}, {"mac": None}, {"mac": ""}, {}, {"uptime_seconds": 3}, pick([RuntimeError("down"), ValueError("v"), OSError("o")])]),
             gen2=pick([{"battery": True}, {"battery": False}, {"x": 1}, {}, pick([RuntimeError("down"), ValueError("v"), OSError("o")])]))
    chosen = set(rng.sample(["adapter_probe", "ssdp", "tls_ssh"], rng.randrange(0, 4))) | pick([{"adapter_probe"}, {"adapter_probe"}, set()])
    adapter, extra = pick(["generic", "x"]), pick([{}, {"k": 1}])
    out = await pipeline_probes._probe_shelly_adapter(chosen, info, "10.0.0.5", adapter, extra)
    return ["shelly", [sorted(chosen), ports, adapter, extra], [out, info]]


loop = asyncio.new_event_loop()
out = []
for _ in range(N):
    LOG.clear()
    kind, req, res = loop.run_until_complete(pick([case_batch, case_parallel, case_shelly])())
    out.append({"kind": kind, "req": jcopy(req), "res": jcopy(res), "log": jcopy(LOG)})


def digest(x):
    return hashlib.sha1(json.dumps(x, default=str, sort_keys=True).encode()).hexdigest()[:20]


result = {"digests": [digest(o) for o in out], "sample": out[:6]}
if os.environ.get("PIPELINE_HEAVY_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(result, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want["digests"]) == len(result["digests"]) == N
for i, (x, y) in enumerate(zip(result["digests"], want["digests"])):
    assert x == y, "call %d differs: %s" % (i, json.dumps(out[i], default=str)[:900])
assert result["sample"] == want["sample"]
c = lambda f: sum(1 for o in out if f(o))  # noqa: E731
b = lambda o: o["kind"] == "batch"  # noqa: E731
p = lambda o: o["kind"] == "parallel"  # noqa: E731
s = lambda o: o["kind"] == "shelly"  # noqa: E731
stats = {"b_names": c(lambda o: b(o) and o["res"]["mdns_names"]), "b_ssdp": c(lambda o: b(o) and o["res"]["upnp_info"]), "b_wsd": c(lambda o: b(o) and o["res"]["wsd_info"]), "b_igmp": c(lambda o: b(o) and o["res"]["igmp_info"]),
         "b_err": c(lambda o: b(o) and any(e[0] == "error" for e in o["log"])), "b_default": c(lambda o: b(o) and o["req"][0] is None), "b_nojobs": c(lambda o: b(o) and not o["log"]),
         "p_timeout": c(lambda o: p(o) and any("scaduta" in str(e) or "ripiego" in str(e) for e in o["log"])), "p_fast": c(lambda o: p(o) and any(e[0] == "fast_ports" for e in o["log"])),
         "p_fastfail": c(lambda o: p(o) and any("ripiego fallita" in str(e) for e in o["log"])), "p_slow": c(lambda o: p(o) and o["res"][2].get("slow_scan")), "p_nohost": c(lambda o: p(o) and "mac" in o["res"][2] and o["res"][2]["mac"] is None),
         "p_all3": c(lambda o: p(o) and any(e[0] == "_run_nmap" for e in o["log"]) and any(e[0] == "protocol_scan" for e in o["log"]) and any(e[0] == "rtsp_probe" for e in o["log"])),
         "s_gen1": c(lambda o: s(o) and o["res"][0][0] == "shelly_gen1"), "s_gen2": c(lambda o: s(o) and any(e[0] == "shelly_gen2.battery_probe" for e in o["log"])), "s_bat": c(lambda o: s(o) and o["res"][1].get("battery") in ("yes", "no")),
         "s_none": c(lambda o: s(o) and not o["log"])}
for key, low in (("b_names", 150), ("b_ssdp", 100), ("b_wsd", 100), ("b_igmp", 100), ("b_err", 150), ("b_default", 40), ("b_nojobs", 20), ("p_timeout", 100), ("p_fast", 80), ("p_fastfail", 10), ("p_slow", 200),
                 ("p_nohost", 100), ("p_all3", 20), ("s_gen1", 80), ("s_gen2", 100), ("s_bat", 150), ("s_none", 100)):
    assert stats[key] >= low, ("scenarios too uniform", key, stats)
print("TUTTO OK")
